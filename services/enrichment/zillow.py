from typing import Optional, Dict, Any

from langchain_core.messages import HumanMessage, SystemMessage

from clients.firecrawl_client import scrape_markdown, search_for_url
from clients import scrape_cache
from services.markdown_utils import slice_around
from schemas.pydantic_schemas import ZillowExtraction

from services.llm_utils import _content_to_text, _extract_json


SOURCE = "zillow"


def _build_query(property_name: str, full_address: str) -> str:
    return f'site:zillow.com "{property_name}" OR "{full_address}"'


def _resolve_url(property_name: str, full_address: str, addr_key: str) -> Optional[Dict[str, Any]]:
    
    """Cached Firecrawl search for the property's zillow.com listing."""
    
    if scrape_cache.has_search_result(SOURCE, property_name, addr_key):
        result = scrape_cache.get_search_result(SOURCE, property_name, addr_key)
        tag = "hit" if (result and result.get("url")) else "hit (negative)"
        print(f"[zillow] search cache {tag}: {property_name!r}")
        return result

    query = _build_query(property_name, full_address)
    print(f"[zillow] firecrawl search: {query}")
    result = search_for_url(query)
    scrape_cache.put_search_result(SOURCE, property_name, addr_key, result)

    return result


def _build_extract_messages(active_listings_block, floorplan_block) -> list:
    sys = SystemMessage(content=(
        "You extract structured data from Zillow building-page markdown sections. "
        "Output ONLY a JSON object — no prose, no fences. Use null when not present."
    ))
    user = HumanMessage(content=(
        "Return JSON with EXACTLY these keys: "
        "active_listings, floorplan_count\n"
        "- active_listings: integer number of currently-available units/listings. "
        "Look near the 'Choose a unit to estimate' line (e.g. 'N units available').\n"
        "- floorplan_count: integer number of distinct floor plans. The line "
        "'N floor plans available' usually contains it directly.\n"
        f"ACTIVE LISTINGS BLOCK:\n{active_listings_block or '(none)'}\n\n"
        f"FLOORPLAN BLOCK:\n{floorplan_block or '(none)'}\n"
    ))
    return [sys, user]


def fetch_zillow_features(
    llm,
    property_name: str,
    full_address: str,
) -> Dict[str, Any]:

    """
    Returns a dict with: active_listings, floorplan_count, manager.
    All values may be None.
    """
    empty = {"active_listings": None, "floorplan_count": None}

    addr_key = full_address

    # 1. Resolve URL via cached Firecrawl search
    result = _resolve_url(property_name, full_address, addr_key)
    url = (result or {}).get("url")
    if not url:
        return empty

    # 2. Scrape — Firecrawl client itself cached by URL
    md = scrape_markdown(url)
    if not md:
        return empty

    active_listings_block = slice_around(md, "Choose a unit to estimate",
                                          before=0, after=1)
    floorplan_block = slice_around(md, "floor plans available",
                                          before=0, after=1)

    # Bail out cheaply if neither anchor matched (often a captcha / blocked page).
    if not active_listings_block and not floorplan_block:
        print(f"[zillow] no anchors matched on {url} — skipping LLM call")
        return empty

    resp = llm.invoke(_build_extract_messages(active_listings_block, floorplan_block))

    try:
        raw = _extract_json(_content_to_text(resp.content))
        parsed = ZillowExtraction.model_validate(raw)
    except Exception as e:
        print(f"[zillow] extraction parse failed: {e}")
        return empty

    return {
        "active_listings": parsed.active_listings,
        "floorplan_count": parsed.floorplan_count,
    }