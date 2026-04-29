import os
import re
import json
from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import ValidationError
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage

from schemas.pydantic_schemas import BuyingTriggerPayload
from services.enrichment.apartments_dot_com import fetch_apartments_features
from services.enrichment.zillow import fetch_zillow_features
from services.enrichment.account_fit_lookup import fetch_account_fit_lookup
from services.llm_utils import _content_to_text, _extract_json, _normalize_bucket

from clients import lead_cache

# ======================================================================

# Produce features
class FeaturePipeline:
    def __init__(self, property_name: str, full_address: str, census_data: Optional[dict] = None):
        self.property_name = property_name
        self.full_address = full_address
        self.census_data = census_data

        self._api_successes = 0
        self._api_attempts = 0

        self.model = 'gemini-2.5-flash-lite'
        self.llm = ChatGoogleGenerativeAI(
            model = self.model,
            temperature = 0.1,
            streaming = False,
            api_key = os.getenv("GOOGLE_API_KEY"),
        )

        # Use Non-flash-lite version for grounded tool calling
        self.llm_grounded = ChatGoogleGenerativeAI(
            model = 'gemini-2.5-flash',
            temperature = 0.1,
            streaming = False,
            api_key = os.getenv("GOOGLE_API_KEY"),
        ).bind_tools([{"google_search": {}}])


        # email llm:
        self.llm_email = ChatGoogleGenerativeAI(
            model = 'gemini-2.5-flash',
            temperature = 0.1,
            streaming = False,
            api_key = os.getenv("GOOGLE_API_KEY"),
        )


    def _record_attempt(self, source: str, success: bool) -> None:
        self._api_attempts += 1
        if success:
            self._api_successes += 1


    def get_account_fit_features(self) -> dict:
        self._apartments = fetch_apartments_features(
            self.llm, self.property_name, self.full_address
        )
        self._record_attempt(
            "apartments",
            any(self._apartments.get(k) is not None for k in
            ("unit_count", "review_count", "manager"))
        )

        self._zillow = fetch_zillow_features(
            self.llm, self.property_name, self.full_address
        )
        self._record_attempt(
            "zillow",
            any(self._zillow.get(k) is not None for k in
                ("active_listings", "floorplan_count")),
        )

        # manager fallback: A -> Z -> None
        manager = self._apartments.get("manager") #or self._zillow.get("manager") or None
        self.managing_company = manager

        lookup = fetch_account_fit_lookup(
            self.llm_grounded, self.property_name, self.full_address, manager
        )
        self._record_attempt(
            "account_fit_lookup",
            lookup.get("manager_portfolio_size") is not None
            or lookup.get("detected_pms_vendor") is not None
            or (lookup.get("property_type") not in (None, "unknown")),
        )

        return {
        "unit_count": self._apartments.get("unit_count"),
        "review_count": self._apartments.get("review_count"),
        "complaint_count": self._apartments.get("complaint_count"),

        "manager": manager,

        "active_listings": self._zillow.get("active_listings"),
        "floorplan_count": self._zillow.get("floorplan_count"),

        "manager_portfolio_size": lookup.get("manager_portfolio_size"),
        "property_type": lookup.get("property_type"),
        "detected_pms_vendor": lookup.get("detected_pms_vendor"),
        }
        

# ======================================================================
    def _payload_to_buying_trigger_kwargs(
        self, p: BuyingTriggerPayload
    ) -> Dict[str, Any]:
        # Soft floor on evidence_confidence: if the model omits it but DID
        # return any URLs, treat as 0.5 so the whole score doesn't cliff to 0.
        any_urls = any([
            p.ownership_change.evidence_urls,
            p.leaseup.evidence_urls,
            p.hiring.evidence_urls,
            p.expansion.evidence_urls,
            p.tech_change.evidence_urls,
        ])
        confidence = float(p.evidence_confidence or (0.5 if any_urls else 0.0))
        return {
            "ownership_change_bucket":   _normalize_bucket(p.ownership_change.bucket),
            "ownership_change_days_ago": p.ownership_change.days_ago,
            "ownership_change_kinds":    p.ownership_change.kinds or None,
            "in_leaseup_or_new_construction": p.leaseup.value,
            "open_leasing_or_ops_roles": p.hiring.open_roles,
            "expansion_bucket":          _normalize_bucket(p.expansion.bucket),
            "expansion_days_ago":        p.expansion.days_ago,
            "tech_change_bucket":        _normalize_bucket(p.tech_change.bucket),
            "tech_change_days_ago":      p.tech_change.days_ago,
            "evidence_confidence":       confidence,
            # Pass-through for reason codes / outreach email
            "_evidence": {
                "ownership_change": p.ownership_change.evidence_urls,
                "leaseup":          p.leaseup.evidence_urls,
                "hiring":           p.hiring.evidence_urls,
                "expansion":        p.expansion.evidence_urls,
                "tech_change":      p.tech_change.evidence_urls,
            },
        }

    def _invoke_with_retry(
        self, messages, retries: int = 1
    ) -> BuyingTriggerPayload:

        last_err: Optional[Exception] = None
        last_text: str = ""

        for attempt in range(retries + 1):
            try:
                response = self.llm_grounded.invoke(messages)
                last_text = _content_to_text(response.content)

                # DEBUG: print the response metadata
                #fr = response.response_metadata.get("finish_reason") if hasattr(response, "response_metadata") else None
                #print(f"[buying_trigger] finish_reason={fr}")
                #print(f"[buying_trigger] response_metadata: {response.response_metadata!r}")
                #print(f"[buying_trigger] content_types: "
                #    f"{[type(p).__name__ for p in response.content] if isinstance(response.content, list) else type(response.content).__name__}")
                # if isinstance(response.content, list):
                #     for i, p in enumerate(response.content):
                #         keys = list(p.keys()) if isinstance(p, dict) else "(str)"
                #         print(f"  part[{i}] keys={keys}")

                # TEMP debug — remove once stable
                # print(f"[buying_trigger] attempt {attempt}: "
                #     f"content_type={type(response.content).__name__}, "
                #     f"text_len={len(last_text)}")
                # if not last_text:
                #     # Useful when content is a list of tool-call parts with no text
                #     print(f"[buying_trigger] raw content: {response.content!r}")


                raw = _extract_json(last_text)
                return BuyingTriggerPayload.model_validate(raw)

            except (json.JSONDecodeError, ValidationError, ValueError) as e:
                last_err = e

                print(f"[buying_trigger] attempt {attempt} parse error: {e}")
                print(f"[buying_trigger] first 400 chars of response:\n{last_text[:400]}")

                if attempt == retries:
                    print(f"[buying_trigger] LLM parse failed: {e}")
                    return BuyingTriggerPayload()

        raise RuntimeError(f"unreachable: {last_err}")


    def get_buying_trigger_features(self) -> dict:
        with open("services/prompts/buying_trigger.md", "r") as f:
            prompt_text = f.read()
        
        # Placeholder for the company name
        self.managing_company = 'Elmington Residential'
        
        filled_prompt = prompt_text.format(
            today_iso = date.today().isoformat(),
            managing_company = self.managing_company,
            property_name = self.property_name,
            full_address = self.full_address,
        )

        system_msg = SystemMessage(
            content = (
                "You are a careful B2B sales researcher."
                "Use Google Search to verify every claim."
                "Prefer 'unknown' over guessing."
                "Output ONLY a single JSON object - no prose, no fences."
            )
        )

        human_msg = HumanMessage(content=filled_prompt)
        payload = self._invoke_with_retry([system_msg, human_msg], retries=3)
        kwargs = self._payload_to_buying_trigger_kwargs(payload)

        self._record_attempt(
            "buying_trigger",
            # Either the LLM rated it's own evidence > 0, or it returned URLs.
            (kwargs.get("evidence_confidence") or 0.0) > 0.0
            or any(kwargs.get("_evidence", {}).values()),
        )

        return kwargs

# ======================================================================

    def get_data_confidence_features(self) -> dict:
        return {
            "property_website_found": bool(
                self.features.get("manager") or
                self.features.get("unit_count") or
                self.features.get("active_listings")
            ),
            "api_success_count": self._api_successes,
            "api_attempt_count": self._api_attempts,
        }

# ======================================================================

    def get_features(self, use_cache: bool = True) -> dict:
        
        if use_cache:
            cached = lead_cache.get_features(self.property_name, self.full_address)
            
            if cached is not None:
                print(f"[feature_pipeline] cache hit: {self.property_name!r}")
                self.features = cached
                return self.features


        self.features = {}
        self._record_attempt("census", bool(self.census_data))

        self.features.update(self.get_account_fit_features())
        self.features.update(self.get_buying_trigger_features())
        self.features["census_data"] = self.census_data
        self.features.update(self.get_data_confidence_features())

        lead_cache.put_features(self.property_name, self.full_address, self.features)
        
        return self.features