from __future__ import annotations

import json
import re
from typing import Any


def parse_json_object(raw_text: str) -> dict[str, Any]:
    """Extract and parse a single JSON object from model output text."""
    text = raw_text.strip()
    if not text:
        raise ValueError("Model returned an empty response")

    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
        raise ValueError("Model JSON output must be an object")
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Model output did not contain a JSON object")

    candidate = text[start : end + 1]
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Could not parse JSON from model output: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Model JSON output must be an object")
    return payload
