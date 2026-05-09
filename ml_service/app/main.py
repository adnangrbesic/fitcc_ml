# ---------------------------------------------------------------------------
# BuyGuardian ML Service — FastAPI Application
# ---------------------------------------------------------------------------
"""FastAPI entrypoint with lifespan management for DB pool, Redis, and scheduler."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.db import init_pool, close_pool
from app.models.isolation_forest import init_redis, close_redis
from app.routes.anomaly import router as anomaly_router
from app.scheduler import start_scheduler, stop_scheduler

# ── Logging ───────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Lifespan ──────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle hooks."""
    logger.info("Starting BuyGuardian ML Service...")

    # Startup
    await init_pool()
    await init_redis()
    start_scheduler()

    logger.info("ML Service ready.")
    yield

    # Shutdown
    logger.info("Shutting down ML Service...")
    stop_scheduler()
    await close_redis()
    await close_pool()
    logger.info("ML Service stopped.")


# ── App ───────────────────────────────────────────────────────────────────

app = FastAPI(
    title="BuyGuardian ML Service",
    description=(
        "Unsupervised Isolation Forest anomaly detection for OLX.ba listing prices. "
        "Provides per-listing anomaly scores with 3-tier fallback: "
        "Isolation Forest → Z-score → LLM overpay_ratio."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(anomaly_router)


@app.get("/")
async def root():
    return {
        "service": "BuyGuardian ML Service",
        "version": "0.1.0",
        "docs": "/docs",
    }
