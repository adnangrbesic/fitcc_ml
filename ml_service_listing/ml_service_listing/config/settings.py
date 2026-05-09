from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


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
    model_path: str
    training_data_path: str
    retrain_enabled: bool
    retrain_iterations: int


def _default_path(relative_path: str) -> str:
    base_dir = Path(__file__).resolve().parents[1]
    candidate = base_dir / relative_path
    alt = base_dir.parent / relative_path

    if candidate.parent.exists() and candidate.parent.is_dir():
        return str(candidate)
    if alt.parent.exists() and alt.parent.is_dir():
        return str(alt)
    return str(candidate)


def _normalize_path(value: str, fallback: str) -> str:
    path = Path(value)
    if path.parent.exists() and path.parent.is_dir():
        return str(path)
    return fallback


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
    default_model_path = _default_path("model/model.cbm")
    default_training_data = _default_path("training/data/listings.json")
    model_path_env = os.getenv("MODEL_PATH")
    training_path_env = os.getenv("TRAINING_DATA_PATH")
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
        model_path=_normalize_path(
            model_path_env,
            default_model_path,
        )
        if model_path_env
        else default_model_path,
        training_data_path=_normalize_path(
            training_path_env,
            default_training_data,
        )
        if training_path_env
        else default_training_data,
        retrain_enabled=_get_bool("RETRAIN_ENABLED", True),
        retrain_iterations=_get_int("RETRAIN_ITERATIONS", 50),
    )
