from __future__ import annotations

import json
import re
from typing import Any


def parse_json_object(raw_text: str) -> dict[str, Any]:
    """Extract and parse a single JSON object from model output text."""
    text = raw_text.strip()
    if not text:
        raise ValueError("Model returned an empty response")

    # Remove markdown code blocks if present
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

    # Try direct parse
    try:
        return _clean_and_load_json(text)
    except Exception:
        pass

    # Extract bracketed content
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Model output did not contain a JSON object")

    candidate = text[start : end + 1]
    try:
        return _clean_and_load_json(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Could not parse JSON from model output: {exc}") from exc

def _clean_and_load_json(text: str) -> dict[str, Any]:
    """Cleans common JSON errors (like trailing commas) before loading."""
    # Remove trailing commas from objects and arrays
    # This regex looks for a comma followed by a closing bracket/brace
    cleaned = re.sub(r",\s*([\]}])", r"\1", text)
    
    payload = json.loads(cleaned)
    if not isinstance(payload, dict):
        raise ValueError("Model JSON output must be an object")
    return payload
