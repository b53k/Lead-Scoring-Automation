import os
import requests
from typing import Optional
from firecrawl import Firecrawl
from clients import scrape_cache

DEFAULT_MAX_AGE_MS = 172_800_000
SEARCH_URL = "https://api.firecrawl.dev/v2/search"

_app: Optional[Firecrawl] = None

def _client() -> Firecrawl:
    global _app
    if _app is None:
        _app = Firecrawl(api_key=os.getenv("FIRECRAWL_API_KEY"))
    return _app


# def scrape_markdown(url: str, max_age_ms: int = DEFAULT_MAX_AGE_MS) -> Optional[str]:
#     """Return markdown for a URL, or None if scrape fails."""
#     try:
#         data = _client().scrape(
#             url,
#             only_main_content=False,
#             max_age=max_age_ms,
#             parsers=["pdf"],
#             formats=["markdown"],
#         )
#         return getattr(data, "markdown", None)
#     except Exception as e:
#         print(f"[firecrawl] scrape failed for {url}: {e}")
#         return None

def scrape_markdown(
    url: str,
    max_age_ms: int = DEFAULT_MAX_AGE_MS,
    use_cache: bool = True,
) -> Optional[str]:

    """Return markdown for a URL, or None if scrape fails. Cached on disk by URL."""

    if use_cache:
        cached = scrape_cache.get_markdown(url)
        if cached is not None:
            print(f"[firecrawl] cache hit: {url}")
            return cached
    try:
        
        data = _client().scrape(
            url,
            only_main_content=False,
            max_age=max_age_ms,
            parsers=["pdf"],
            formats=["markdown"],
        )
        print (f"Firecrawl scraped: {url}")

        md = getattr(data, "markdown", None)

    except Exception as e:
        print(f"[firecrawl] scrape failed for {url}: {e}")
        return None
        
    if md and use_cache:
        scrape_cache.put_markdown(url, md)
    return md


def search_for_url(
    query: str,
    *,
    limit: int = 1,
    timeout: int = 30,
    max_age_ms: int = DEFAULT_MAX_AGE_MS,
) -> Optional[str]:
    
    """Search for a URL matching the query."""

    api_key = os.getenv("FIRECRAWL_API_KEY")

    payload = {
        "query": query,
        "sources": ["web"],
        "categories": [],
        "limit": limit,
        "scrapeOptions": {
            "onlyMainContent": False,
            "maxAge": max_age_ms,
            "parsers": ["pdf"],
            "formats": [],
        },
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(SEARCH_URL, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        body = resp.json() or {}

    except (requests.RequestException, ValueError) as e:
        print (f"[firecrawl] search failed for {query}: {e}")
        return None
    
    web = (body.get("data") or {}).get("web") or []
    if not web:
        return None

    top = web[0]

    return {
        "url": top.get("url"),
        "title": top.get("title"),
        "description": top.get("description"),
    }