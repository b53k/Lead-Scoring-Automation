"""
    Feature cache for FeaturePipeline.get_features() outputs.
    Independent of scrape_cache so 'force fresh LLM' can clear this without
    touching the Firecrawl scrape/search cache.
"""

import os
import re
import json
import threading
from datetime import datetime, timezone
from typing import Optional, Dict, Any

DEFAULT_CACHE_PATH = os.path.join("data", "lead_cache.json")

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
            print(f"[lead_cache] could not load {_cache_path}: {e} -- starting fresh")
            _cache = {}
    else:
        _cache = {}
    _cache.setdefault("features", {})

    return _cache

def _save() -> None:
    os.makedirs(os.path.dirname(_cache_path) or ".", exist_ok=True)
    tmp = _cache_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(_cache, f, indent=2, default=str)
    os.replace(tmp, _cache_path)

def _norm(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s


def feature_key(property_name: str, full_address: str) -> str:
    return f"{_norm(property_name)}|{_norm(full_address)}"


def has_features(property_name: str, full_address: str) -> bool:
    with _lock:
        return feature_key(property_name, full_address) in _load()["features"]


def get_features(property_name: str, full_address: str) -> Optional[Dict[str, Any]]:
    with _lock:
        entry = _load()["features"].get(feature_key(property_name, full_address))
        return entry["features"] if entry else None


def put_features(property_name: str, full_address: str,
                  features: Dict[str, Any]) -> None:
    with _lock:
        _load()["features"][feature_key(property_name, full_address)] = {
            "features": features,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        _save()


def invalidate(property_name: str, full_address: str) -> None:
    """Drop one entry — used by the 'force fresh LLM' UI toggle."""
    with _lock:
        _load()["features"].pop(feature_key(property_name, full_address), None)
        _save()


def clear() -> None:
    with _lock:
        _load()["features"].clear()
        _save()


def stats() -> dict:
    with _lock:
        return {"feature_rows_cached": len(_load()["features"])}

# --------------------------- Outreach Email Cache ---------------------------

def get_email(property_name: str, full_address: str) -> Optional[Dict[str, Any]]:
    with _lock:
        entry = _load()["features"].get(feature_key(property_name, full_address))
        return entry.get("outreach_email") if entry else None


def put_email(property_name: str, full_address: str,
               email: Dict[str, Any]) -> None:
    """Attach/replace the email on an existing entry. No-op if features missing."""
    with _lock:
        entries = _load()["features"]
        key = feature_key(property_name, full_address)
        if key not in entries:
            print(f"[lead_cache] put_email skipped: no features entry for {key}")
            return
        entries[key]["outreach_email"] = email
        _save()


def invalidate_email(property_name: str, full_address: str) -> None:
    """Drop only the email; keep features intact (used by the Regenerate button)."""
    with _lock:
        entry = _load()["features"].get(feature_key(property_name, full_address))
        if entry and "outreach_email" in entry:
            entry.pop("outreach_email", None)
            _save()

