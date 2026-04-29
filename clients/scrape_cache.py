"""
Tiny JSON-on-disk cache for Firecrawl scrapes and Gemini-resolved URLs.

Two independent namespaces in one file:
  - url_to_markdown:  url -> {"markdown": str, "fetched_at": iso_ts}
  - property_to_url:  "<source>::<key>" -> url (or None for negative cache)
        where key = normalized "property_name|street_address"

Process-local; not concurrency-safe. Fine for a single batch run.
"""
import os
import json
import re
import threading
from datetime import datetime, timezone
from typing import Optional

DEFAULT_CACHE_PATH = os.path.join("data", "scrape_cache.json")

_lock = threading.Lock()
_cache_path: str = DEFAULT_CACHE_PATH
_cache: Optional[dict] = None


def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    if os.path.exists(_cache_path):
        try:
            with open(_cache_path, "r") as f:
                _cache = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[scrape_cache] could not load {_cache_path}: {e} -- starting fresh")
            _cache = {}
    else:
        _cache = {}
    _cache.setdefault("url_to_markdown", {})
    _cache.setdefault("search_results", {})
    return _cache


def _save() -> None:
    os.makedirs(os.path.dirname(_cache_path) or ".", exist_ok=True)
    tmp = _cache_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(_cache, f, indent=2)
    os.replace(tmp, _cache_path)   # atomic — survives Ctrl+C mid-write


def _norm(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s


def property_key(source: str, property_name: str, street_address: str) -> str:
    return f"{source.lower()}::{_norm(property_name)}|{_norm(street_address)}"


# ---------- URL -> markdown ----------

def get_markdown(url: str) -> Optional[str]:
    with _lock:
        entry = _load()["url_to_markdown"].get(url)
        return entry["markdown"] if entry else None


def put_markdown(url: str, markdown: str) -> None:
    with _lock:
        _load()["url_to_markdown"][url] = {
            "markdown": markdown,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        _save()


# ---------- (source, property) -> URL ----------

# def has_url_for_property(source: str, property_name: str, street_address: str) -> bool:
#     """True if we previously resolved this property — even if the answer was None."""
#     with _lock:
#         return property_key(source, property_name, street_address) in _load()["property_to_url"]


# def get_url_for_property(source: str, property_name: str, street_address: str) -> Optional[str]:
#     with _lock:
#         return _load()["property_to_url"].get(
#             property_key(source, property_name, street_address)
#         )


# def put_url_for_property(source: str, property_name: str, street_address: str,
#                           url: Optional[str]) -> None:
#     """Store URL (or None to remember a confirmed-not-found)."""
#     with _lock:
#         _load()["property_to_url"][
#             property_key(source, property_name, street_address)
#         ] = url
#         _save()



# ---------- search results FIRECRWAL----------

def get_search_result(source: str, property_name: str, street_address: str
                       ) -> Optional[dict]:
    with _lock:
        return _load()["search_results"].get(
            property_key(source, property_name, street_address)
        )


def has_search_result(source: str, property_name: str, street_address: str) -> bool:
    """True if we previously searched for this property — even if result was None."""
    with _lock:
        return property_key(source, property_name, street_address) in _load()["search_results"]


def put_search_result(source: str, property_name: str, street_address: str,
                       result: Optional[dict]) -> None:
    """Store a search hit (or None to remember a confirmed-no-result)."""
    payload = None
    if result:
        payload = {
            "url":         result.get("url"),
            "title":       result.get("title"),
            "description": result.get("description"),
            "fetched_at":  datetime.now(timezone.utc).isoformat(),
        }
    with _lock:
        _load()["search_results"][
            property_key(source, property_name, street_address)
        ] = payload
        _save()


# ---------- stats ----------

def stats() -> dict:
    with _lock:
        c = _load()
        urls = c["url_to_markdown"]
        return {
            "scrapes_cached": len(c["url_to_markdown"]),
            "properties_resolved": len(urls),
            "properties_with_url": sum(1 for v in urls.values() if v),
            "properties_no_url": sum(1 for v in urls.values() if v is None),
        }