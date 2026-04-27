from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


_ENV_LOADED = False


class LLMConfigurationError(ValueError):
    """Raised when LLM enrichment configuration is invalid."""


@dataclass(frozen=True)
class LLMRuntimeConfig:
    provider: str
    model: str
    base_url: str
    api_key: str
    timeout_s: float
    max_retries: int
    temperature: float
    validate_output_schema: bool
    category: str
    prompt_template_path: Path
    output_template_path: Path
    output_schema_path: Path


def _load_env_file(path: Path) -> None:
    """Load KEY=VALUE pairs from a .env-like file into process env.

    Existing environment variables are preserved (shell-exported values win).
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue

        value = value.strip()

        # Remove wrapping single/double quotes.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]

        os.environ.setdefault(key, value)


def _load_runtime_env_once() -> None:
    """Load scraper env file once, independent of current working directory."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True

    # config.py lives in scraper/llm; project root is scraper_engine.
    project_root = Path(__file__).resolve().parents[2]

    env_file_hint = os.getenv("SCRAPER_ENV_FILE", ".env")
    hint_path = Path(env_file_hint).expanduser()

    candidates: list[Path] = []
    if hint_path.is_absolute():
        candidates.append(hint_path)
    else:
        candidates.append(project_root / hint_path)
        candidates.append(Path.cwd() / hint_path)

    # Final fallback to the default local project env file.
    candidates.append(project_root / ".env")

    seen: set[str] = set()
    for candidate in candidates:
        resolved = str(candidate.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)

        if candidate.exists() and candidate.is_file():
            _load_env_file(candidate)
            break


def _read_float(name: str, default: float, *, min_value: float, max_value: float | None = None) -> float:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default

    try:
        parsed = float(value)
    except ValueError as exc:
        raise LLMConfigurationError(f"{name} must be a float, got: {value}") from exc

    if parsed < min_value:
        raise LLMConfigurationError(f"{name} must be >= {min_value}, got: {parsed}")
    if max_value is not None and parsed > max_value:
        raise LLMConfigurationError(f"{name} must be <= {max_value}, got: {parsed}")
    return parsed


def _read_int(name: str, default: int, *, min_value: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default

    try:
        parsed = int(value)
    except ValueError as exc:
        raise LLMConfigurationError(f"{name} must be an integer, got: {value}") from exc

    if parsed < min_value:
        raise LLMConfigurationError(f"{name} must be >= {min_value}, got: {parsed}")
    return parsed


def _read_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False

    raise LLMConfigurationError(
        f"{name} must be a boolean (true/false), got: {value}"
    )


def _resolve_path(raw: str | None, default_path: Path) -> Path:
    if raw and raw.strip():
        return Path(raw).expanduser().resolve()
    return default_path.resolve()


def build_config(
    *,
    category: str,
    prompt_template_path: str | None = None,
    output_template_path: str | None = None,
    output_schema_path: str | None = None,
    validate_output_schema: bool | None = None,
) -> LLMRuntimeConfig:
    _load_runtime_env_once()

    provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
    if provider not in {"ollama", "openai", "openai_compat"}:
        raise LLMConfigurationError(
            "LLM_PROVIDER must be one of: ollama, openai, openai_compat"
        )

    model = os.getenv("LLM_MODEL", "llama3").strip()
    if not model:
        raise LLMConfigurationError("LLM_MODEL cannot be empty")

    timeout_s = _read_float("LLM_TIMEOUT_SEC", 300.0, min_value=1.0)
    max_retries = _read_int("LLM_MAX_RETRIES", 2, min_value=0)
    temperature = _read_float("LLM_TEMPERATURE", 0.0, min_value=0.0, max_value=1.0)
    env_validate_output_schema = _read_bool("LLM_VALIDATE_OUTPUT_SCHEMA", True)
    effective_validate_output_schema = (
        env_validate_output_schema
        if validate_output_schema is None
        else validate_output_schema
    )

    default_base_url = "http://localhost:11434/v1" if provider == "ollama" else "https://api.openai.com/v1"
    base_url = os.getenv("LLM_BASE_URL", default_base_url).strip()
    if not base_url:
        raise LLMConfigurationError("LLM_BASE_URL cannot be empty")

    default_api_key = "ollama" if provider == "ollama" else ""
    api_key = os.getenv("LLM_API_KEY", default_api_key).strip()
    if not api_key:
        raise LLMConfigurationError(
            "LLM_API_KEY is required for the selected provider"
        )

    template_root = Path(__file__).resolve().parent.parent / "llm_templates" / category
    resolved_prompt_template = _resolve_path(prompt_template_path, template_root / "prompt.txt")
    resolved_output_template = _resolve_path(output_template_path, template_root / "output_template.json")
    resolved_output_schema = _resolve_path(output_schema_path, template_root / "output_schema.json")

    for path, name in (
        (resolved_prompt_template, "prompt template"),
        (resolved_output_template, "output template"),
    ):
        if not path.exists():
            raise LLMConfigurationError(f"Missing {name} file: {path}")

    if effective_validate_output_schema and not resolved_output_schema.exists():
        raise LLMConfigurationError(f"Missing output schema file: {resolved_output_schema}")

    return LLMRuntimeConfig(
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
        timeout_s=timeout_s,
        max_retries=max_retries,
        temperature=temperature,
        validate_output_schema=effective_validate_output_schema,
        category=category,
        prompt_template_path=resolved_prompt_template,
        output_template_path=resolved_output_template,
        output_schema_path=resolved_output_schema,
    )
