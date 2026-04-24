from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any


class TemplateLoadError(ValueError):
    """Raised when prompt or JSON template files cannot be loaded."""


def _load_python_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("llm_prompt_module", path)
    if spec is None or spec.loader is None:
        raise TemplateLoadError(f"Could not load Python prompt template: {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_prompt_template(path: Path) -> str:
    if path.suffix.lower() == ".py":
        module = _load_python_module(path)
        prompt_value = getattr(module, "PROMPT_TEMPLATE", None)
        if not isinstance(prompt_value, str) or not prompt_value.strip():
            raise TemplateLoadError(
                f"Python template {path} must define non-empty PROMPT_TEMPLATE"
            )
        return prompt_value

    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise TemplateLoadError(f"Prompt template is empty: {path}")
    return text


def load_json_document(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TemplateLoadError(f"Invalid JSON file {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise TemplateLoadError(f"JSON file must contain an object at top level: {path}")
    return payload


def render_user_prompt(
    *,
    prompt_template: str,
    output_template: dict[str, Any],
    listing_payload: dict[str, Any],
) -> str:
    output_template_json = json.dumps(output_template, indent=2, ensure_ascii=False)
    listing_json = json.dumps(listing_payload, indent=2, ensure_ascii=False, default=str)

    rendered = prompt_template

    if "{{OUTPUT_TEMPLATE}}" in rendered:
        rendered = rendered.replace("{{OUTPUT_TEMPLATE}}", output_template_json)
    else:
        rendered = f"{rendered}\n\n//OUTPUT FORMAT\n{output_template_json}"

    if "{{ARTICLE_LISTING}}" in rendered:
        rendered = rendered.replace("{{ARTICLE_LISTING}}", listing_json)
    else:
        rendered = f"{rendered}\n\n//ARTICLE LISTING\n{listing_json}"

    return rendered
