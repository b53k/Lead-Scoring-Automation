from typing import Dict, Any, Optional
from langchain_core.messages import HumanMessage, SystemMessage
from schemas.pydantic_schemas import AccountFitLookup
from services.llm_utils import _content_to_text, _extract_json

def fetch_account_fit_lookup(
    llm_grounded,
    property_name: str,
    full_address: str,
    manager: Optional[str],
) -> Dict[str, Any]:

    sys = SystemMessage(content=(
        "You are a careful B2B sales researcher. Use the google_search tool. "
        "Do NOT answer from prior knowledge. "
        "After your searches, output ONLY a single JSON object as your final text response "
        "- no prose, no fences."
    ))
    
    user = HumanMessage(content=f"""\
    Property: {property_name}
    Address:  {full_address}
    Manager:  {manager or 'unknown'}

    Answer THREE independent questions, each with its own search.

    Q1. manager_portfolio_size
        Issue this query verbatim:
        "{manager}" units OR doors OR "managed properties"
        Then prefer numbers from the manager's own website, NMHC top-50 lists,
        or recent press releases. Take the largest verified figure.


    Q2. property_type
        Issue this query verbatim:
        "{property_name}" "{full_address}" student OR senior OR affordable OR multifamily
        Map to one of:
        [multifamily, student_housing, affordable_housing, senior_housing,
        single_family_home, commercial_office, hotel, unknown]


    Q3. detected_pms_vendor
        Issue this query verbatim:
        "{manager}" Yardi OR RealPage OR Entrata OR AppFolio OR Buildium OR ResMan
        Only fill this if a result EXPLICITLY names a PMS the manager uses.
        "Hiring someone with Yardi experience" counts; speculation does NOT.


    Return JSON with EXACTLY this shape — every numeric/vendor field has a sibling
    evidence_url that MUST be a real URL you saw in search results, or null:


    {{
    "manager_portfolio_size":    <int or null>,
    "property_type":             "<one of the enum values>",
    "detected_pms_vendor":       "<vendor name or null>",
    }}
    """)
    
    # user = HumanMessage(content=(
    #     f"Property: {property_name}\nAddress: {full_address}\n"
    #     f"Manager: {manager or 'unknown'}\n\n"
    #     "Return JSON object with EXACTLY these keys:\n"
    #     "- manager_portfolio_size: total units the manager runs NATIONWIDE "
    #     "properties (integer, or null)\n"
    #     "- property_type: one of [multifamily, student_housing, "
    #     "affordable_housing, senior_housing, single_family_home, "
    #     "commercial_office, hotel, unknown]\n"
    #     "- detected_pms_vendor: PMS / leasing-tech vendor in use at this "
    #     "property if any reliable mention exists (e.g. Yardi, RealPage, "
    #     "Entrata, AppFolio, Buildium, ResMan), else null\n"
    # ))
    try:
        raw = _extract_json(_content_to_text(llm_grounded.invoke([sys, user]).content))
        parsed = AccountFitLookup.model_validate(raw)
    except Exception as e:
        print(f"[account_fit_lookup] parse failed: {e}")
        return {"manager_portfolio_size": None,
                "property_type": "unknown",
                "detected_pms_vendor": None}

    return parsed.model_dump()