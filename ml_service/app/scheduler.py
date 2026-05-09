# ---------------------------------------------------------------------------
# BuyGuardian ML Service — Periodic Retraining Scheduler
# ---------------------------------------------------------------------------
"""APScheduler-based periodic retraining of all Isolation Forest models.

Runs every N hours (default: 6), iterating over all products with enough
listings and retraining their IF models. Each product uses its category's
contamination override if set.
"""

from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.db import fetch_all_product_ids_with_min_listings
from app.models.isolation_forest import train_model_for_product

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _retrain_all_products() -> None:
    """Fetch all eligible products and retrain their IF models."""
    logger.info("=== Scheduled retraining started ===")
    products = await fetch_all_product_ids_with_min_listings(settings.min_listings_for_iforest)
    trained = 0
    errors = 0

    for product in products:
        try:
            pid = product["product_id"]
            contamination = product.get("contamination", settings.if_contamination)
            n = await train_model_for_product(pid, contamination)
            if n >= settings.min_listings_for_iforest:
                trained += 1
            logger.debug(
                "Retrained %s: %d listings",
                product.get("canonical_name", str(pid)),
                n,
            )
        except Exception:
            errors += 1
            logger.exception("Failed to retrain product %s", product.get("product_id"))

    logger.info(
        "=== Scheduled retraining completed: %d products trained, %d errors ===",
        trained,
        errors,
    )


def start_scheduler() -> AsyncIOScheduler:
    """Start the periodic retraining scheduler."""
    global _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _retrain_all_products,
        trigger=IntervalTrigger(hours=settings.retrain_interval_hours),
        id="retrain_all_iforest",
        name="Retrain all Isolation Forest models",
        replace_existing=True,
        max_instances=1,  # Prevent overlap
    )
    _scheduler.start()
    logger.info(
        "Scheduler started: retraining every %d hours",
        settings.retrain_interval_hours,
    )
    return _scheduler


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler stopped")
