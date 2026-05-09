# ---------------------------------------------------------------------------
# BuyGuardian ML Service — Configuration
# ---------------------------------------------------------------------------
"""Environment-based configuration for the ML anomaly detection service."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All config is pulled from environment variables with sensible defaults."""

    # ── Database ──────────────────────────────────────────────────────────
    database_url: str = "postgresql://postgres:postgres@db:5432/buyguardian"

    # ── Redis ─────────────────────────────────────────────────────────────
    redis_url: str = "redis://redis:6379"
    model_cache_ttl_seconds: int = 86400  # 24h — models refreshed every 6h anyway

    # ── Isolation Forest Defaults ─────────────────────────────────────────
    if_contamination: float = 0.10
    if_n_estimators: int = 200
    if_max_samples: str = "auto"
    if_random_state: int = 42

    # ── Thresholds ────────────────────────────────────────────────────────
    min_listings_for_iforest: int = 5
    min_listings_for_zscore: int = 3

    # ── Scheduler ─────────────────────────────────────────────────────────
    retrain_interval_hours: int = 6

    # ── Service ───────────────────────────────────────────────────────────
    log_level: str = "INFO"

    model_config = {"env_prefix": "", "case_sensitive": False}


settings = Settings()
