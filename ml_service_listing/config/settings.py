from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    api_base_url: str
    api_key: str | None
    api_key_header: str
    unscored_endpoint: str
    score_endpoint: str
    score_payload_mode: str
    timeout_seconds: float
    batch_size: int
    log_level: str
    verify_ssl: bool
    poll_interval_seconds: float


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def load_settings() -> Settings:
    base_url = os.getenv("API_BASE_URL", "http://localhost:5000").rstrip("/")
    return Settings(
        api_base_url=base_url,
        api_key=os.getenv("API_KEY"),
        api_key_header=os.getenv("API_KEY_HEADER", "X-API-Key"),
        unscored_endpoint=os.getenv("UNSCORED_ENDPOINT", "/api/listings/unscored"),
        score_endpoint=os.getenv("SCORE_ENDPOINT", "/api/listings/score-n"),
        score_payload_mode=os.getenv("SCORE_PAYLOAD_MODE", "map").lower(),
        timeout_seconds=_get_float("REQUEST_TIMEOUT_SECONDS", 10.0),
        batch_size=_get_int("BATCH_SIZE", 50),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        verify_ssl=_get_bool("VERIFY_SSL", True),
        poll_interval_seconds=_get_float("POLL_INTERVAL_SECONDS", 300.0),
    )
