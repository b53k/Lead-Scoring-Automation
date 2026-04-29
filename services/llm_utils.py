import re
import json
from typing import Any, Dict, List, Optional

# Helper functions

VALID_BUCKETS = {
            "last_30_days", "last_90_days", "last_180_days",
            "last_365_days", "older", "unknown",
}


def _content_to_text(content: Any) -> str:
    """
    Grounded Gemini calls sometimes return content as a list of parts
    (str fragments and/or dicts with a 'text' key). Flatten to a single str.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict) and isinstance(p.get("text"), str):
                parts.append(p["text"])
        return "".join(parts)
    return str(content) if content is not None else ""


def _extract_json(text: str) -> Dict[str, Any]:
    """Pull a JSON object out of model output that may include fences or prose."""
    if not text:
        raise ValueError("empty model response")
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))
    # Fall back to the largest top-level {...} block.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"no JSON object found in: {text[:200]}")
    return json.loads(text[start : end + 1])


def _normalize_bucket(bucket: Optional[str]) -> Optional[str]:
    if not bucket:
        return None
    b = bucket.strip().lower()
    return b if b in VALID_BUCKETS else "unknown"