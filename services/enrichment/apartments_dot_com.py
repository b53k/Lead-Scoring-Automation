from typing import Optional, Dict, Any

from langchain_core.messages import HumanMessage, SystemMessage

from clients.firecrawl_client import scrape_markdown, search_for_url
from clients import scrape_cache
from services.markdown_utils import slice_section, slice_around
from schemas.pydantic_schemas import ApartmentsExtraction

from services.llm_utils import _content_to_text, _extract_json


SOURCE = "apartments"

def _build_query(property_name: str, full_address: str) -> str:
    return f'site:apartments.com "{property_name}" OR "{full_address}"'


def _resolve_url(property_name: str, full_address: str, addr_key: str) -> Optional[Dict[str, Any]]:
    
    """Cached Firecrawl search for the property's apartments.com listing."""
    
    if scrape_cache.has_search_result(SOURCE, property_name, addr_key):
        result = scrape_cache.get_search_result(SOURCE, property_name, addr_key)
        tag = "hit" if (result and result.get("url")) else "hit (negative)"
        print(f"[apartments] search cache {tag}: {property_name!r}")
        return result

    query = _build_query(property_name, full_address)
    print(f"[apartments] firecrawl search: {query}")
    result = search_for_url(query)
    scrape_cache.put_search_result(SOURCE, property_name, addr_key, result)

    return result



def _build_extract_messages(property_info, review_block, manager_block) -> list:
    sys = SystemMessage(content=(
        "You extract structured data from apartments.com markdown sections. "
        "Output ONLY a JSON object — no prose, no fences. Use null when not present."
    ))
    user = HumanMessage(content=(
        "Return JSON with EXACTLY these keys: "
        "unit_count, review_count, 1_star_count, 2_star_count, manager.\n"
        "- unit_count: integer total units at the property (look for 'N units')\n"
        "- review_count: integer total number of renter reviews\n"
        "- 1_star_count: integer count of 1-star reviews\n"
        "- 2_star_count: integer count of 2-star reviews\n"
        "- manager: property management company name (from the logo alt text or "
        "image filename, e.g. 'asset-living-logo.jpg' -> 'Asset Living')\n\n"
        f"PROPERTY INFO SECTION:\n{property_info or '(none)'}\n\n"
        f"REVIEW BLOCK:\n{review_block or '(none)'}\n\n"
        f"MANAGER BLOCK:\n{manager_block or '(none)'}\n"
    ))
    return [sys, user]


def fetch_apartments_features(
    llm,
    property_name: str,
    full_address: str,
) -> Dict[str, Any]:

    """
    Returns a dict with: unit_count, review_count, complaint_count, manager.
    All values may be None.
    """

    empty = {"unit_count": None, "review_count": None,
             "complaint_count": None, "manager": None}

    addr_key = full_address

    # 1. Resolve URL via cached Firecrawl search...because Gemini sucks!
    result = _resolve_url(property_name, full_address, addr_key)
    url = (result or {}).get("url")
    if not url:
        return empty

    # 2. Scrape - Firecrawl client itself cached by URL
    md = scrape_markdown(url)
    if not md:
        return empty

    property_info = slice_section(md, "Property Information")
    review_block = slice_around(md, "Reviews for", before=0, after=30)
    manager_block = slice_around(md, "Property Management Company Logo",
                                  before=0, after=2)

    resp = llm.invoke(_build_extract_messages(property_info, review_block, manager_block))

    try:
        raw = _extract_json(_content_to_text(resp.content))
        parsed = ApartmentsExtraction.model_validate(raw)
    except Exception as e:
        print(f"[apartments] extraction parse failed: {e}")
        return empty

    one = parsed.one_star_count or 0
    two = parsed.two_star_count or 0
    complaint_count = (one + two)

    return {
        "unit_count": parsed.unit_count,
        "review_count": parsed.review_count,
        "complaint_count": complaint_count,
        "manager": parsed.manager,
    }