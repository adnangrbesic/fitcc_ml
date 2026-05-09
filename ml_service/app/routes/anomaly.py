# ---------------------------------------------------------------------------
# BuyGuardian ML Service — API Routes
# ---------------------------------------------------------------------------
"""FastAPI routes for anomaly detection scoring and model management."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models.isolation_forest import (
    AnomalyResult,
    score_listing,
    score_product_batch,
    train_model_for_product,
)
from app.db import fetch_all_product_ids_with_min_listings
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/anomaly", tags=["anomaly"])


# ── Request / Response Models ─────────────────────────────────────────────


class AnomalyResponse(BaseModel):
    """Serializable response for a single anomaly result."""

    item_id: str
    product_id: str | None
    anomaly_score: float
    is_anomaly: bool
    anomaly_type: str | None
    features: dict[str, float]
    confidence: str
    product_median_price: float
    product_listing_count: int
    method: str


class BatchRequest(BaseModel):
    product_id: str


class RetrainRequest(BaseModel):
    product_id: str | None = None  # None = retrain all


class RetrainResponse(BaseModel):
    status: str
    products_trained: int
    total_listings: int


class HealthResponse(BaseModel):
    status: str
    version: str = "0.1.0"


# ── Helpers ───────────────────────────────────────────────────────────────


def _result_to_response(result: AnomalyResult) -> AnomalyResponse:
    return AnomalyResponse(
        item_id=result.item_id,
        product_id=result.product_id,
        anomaly_score=result.anomaly_score,
        is_anomaly=result.is_anomaly,
        anomaly_type=result.anomaly_type,
        features=result.features,
        confidence=result.confidence,
        product_median_price=result.product_median_price,
        product_listing_count=result.product_listing_count,
        method=result.method,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Service health check."""
    return HealthResponse(status="ok")


@router.post("/score/{item_id}", response_model=AnomalyResponse)
async def score_single(item_id: str):
    """Score a single listing for price anomaly.

    Implements the 3-tier fallback:
        - N >= 5: Isolation Forest (8 features)
        - 3 <= N < 5: Z-score (price only)
        - N < 3: LLM overpay_ratio passthrough
    """
    result = await score_listing(item_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Listing '{item_id}' not found or has no linked product.",
        )
    return _result_to_response(result)


@router.post("/batch", response_model=list[AnomalyResponse])
async def score_batch(request: BatchRequest):
    """Score all active listings for a product in one batch."""
    try:
        results = await score_product_batch(request.product_id)
    except Exception as e:
        logger.error("Batch scoring failed for product %s: %s", request.product_id, e)
        raise HTTPException(status_code=500, detail=str(e))

    return [_result_to_response(r) for r in results]


@router.post("/retrain", response_model=RetrainResponse)
async def retrain(request: RetrainRequest):
    """Retrain Isolation Forest model(s).

    - If product_id is provided, retrain only that product.
    - If product_id is None, retrain all products with >= min_listings.
    """
    total_products = 0
    total_listings = 0

    if request.product_id:
        n = await train_model_for_product(request.product_id)
        total_products = 1 if n >= settings.min_listings_for_iforest else 0
        total_listings = n
    else:
        # Retrain all eligible products
        products = await fetch_all_product_ids_with_min_listings(settings.min_listings_for_iforest)
        for product in products:
            try:
                pid = product["product_id"]
                contamination = product.get("contamination", settings.if_contamination)
                n = await train_model_for_product(pid, contamination)
                total_listings += n
                total_products += 1
                logger.info(
                    "Retrained %s (%d listings)",
                    product.get("canonical_name", pid),
                    n,
                )
            except Exception as e:
                logger.error("Failed to retrain product %s: %s", product["product_id"], e)

    return RetrainResponse(
        status="completed",
        products_trained=total_products,
        total_listings=total_listings,
    )
