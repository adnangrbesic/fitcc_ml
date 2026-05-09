# ---------------------------------------------------------------------------
# BuyGuardian ML Service — Isolation Forest Anomaly Detector
# ---------------------------------------------------------------------------
"""Core ML module: trains per-product Isolation Forest models, caches them in
Redis, and provides scoring with graceful fallback to Z-score / LLM.

Anomaly type derivation:
    After predict(), the feature with the largest |z-score| from the group
    determines the anomaly type label for UX purposes.
"""

from __future__ import annotations

import io
import logging
import pickle
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import numpy as np
import redis.asyncio as aioredis
from sklearn.ensemble import IsolationForest

from app.config import settings
from app.db import (
    fetch_listings_for_product,
    fetch_price_history,
    fetch_product_by_item_id,
)
from app.features.engineering import (
    FEATURE_NAMES,
    build_feature_matrix,
    compute_zscore_price_only,
    fit_scaler,
    transform_with_scaler,
    _safe_float,
    _extract_from_metadata,
)

logger = logging.getLogger(__name__)

# Global Redis client (initialized in main.py lifespan)
_redis: aioredis.Redis | None = None


async def init_redis() -> None:
    global _redis
    _redis = aioredis.from_url(settings.redis_url, decode_responses=False)
    logger.info("Redis client connected (%s)", settings.redis_url)


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


def _model_key(product_id: UUID | str) -> str:
    return f"iforest:model:{product_id}"


def _scaler_key(product_id: UUID | str) -> str:
    return f"iforest:scaler:{product_id}"


# ── Data classes ──────────────────────────────────────────────────────────


@dataclass
class AnomalyResult:
    """Result of anomaly scoring for a single listing."""

    item_id: str
    product_id: str | None
    anomaly_score: float  # Raw decision_function score (lower = more anomalous)
    is_anomaly: bool
    anomaly_type: str | None  # "underpriced", "overpriced", "suspicious_profile", etc.
    features: dict[str, float]
    confidence: str  # "high", "medium", "low", "insufficient"
    product_median_price: float
    product_listing_count: int
    method: str  # "isolation_forest", "zscore", "llm_fallback"


# ── Anomaly Type Derivation ──────────────────────────────────────────────


def _derive_anomaly_type(
    feature_vector: np.ndarray,
    group_mean: np.ndarray,
    group_std: np.ndarray,
) -> str:
    """Determine the anomaly type from the dominant outlier feature.

    Calculates per-feature z-scores and picks the one with the largest
    absolute deviation to label the anomaly type.
    """
    # Avoid division by zero
    safe_std = np.where(group_std < 1e-9, 1.0, group_std)
    z_scores = (feature_vector - group_mean) / safe_std

    # Map feature index → anomaly type rules
    abs_z = np.abs(z_scores)
    dominant_idx = int(np.argmax(abs_z))
    dominant_z = z_scores[dominant_idx]
    dominant_feature = FEATURE_NAMES[dominant_idx]

    # Price deviation has directional meaning
    if dominant_feature == "price_deviation":
        if dominant_z < -2.0:
            return "underpriced"
        elif dominant_z > 2.0:
            return "overpriced"
        return "price_anomaly"

    # Spam score
    if dominant_feature == "spam_score" and feature_vector[7] > 0.8:
        return "suspicious_description"

    # Seller reliability near zero + underpriced
    if dominant_feature == "seller_reliability" and feature_vector[3] < 0.5:
        if feature_vector[0] < -0.2:  # price_deviation
            return "suspicious_profile"
        return "unverified_seller"

    # Staleness: very new listing with extreme price
    if dominant_feature == "listing_staleness" and feature_vector[5] < 2:
        if feature_vector[0] < -0.3:  # price_deviation
            return "too_good_to_be_true"

    # Condition-to-price mismatch
    if dominant_feature == "condition_to_price":
        if dominant_z > 2.0:
            return "condition_price_mismatch"

    # Generic fallback
    return f"anomaly_{dominant_feature}"


# ── Training ─────────────────────────────────────────────────────────────


async def train_model_for_product(
    product_id: UUID | str,
    contamination: float | None = None,
) -> int:
    """Train an Isolation Forest model for a specific product group.

    Fetches all active listings, builds the feature matrix, fits IF + scaler,
    and caches both in Redis.

    Returns:
        Number of listings in the training set.
    """
    product_id_str = str(product_id)
    listings = await fetch_listings_for_product(product_id)

    if len(listings) < settings.min_listings_for_iforest:
        logger.info(
            "Product %s has %d listings (< %d minimum). Skipping IF training.",
            product_id_str,
            len(listings),
            settings.min_listings_for_iforest,
        )
        return len(listings)

    # Gather price histories for all listings
    price_histories: dict[str, list[float]] = {}
    for listing in listings:
        lid = str(listing["listing_id"])
        price_histories[lid] = await fetch_price_history(listing["listing_id"])

    # Compute median price
    prices = [float(l["price"]) for l in listings if l["price"] and float(l["price"]) > 0]
    if not prices:
        logger.warning("Product %s: all prices are zero. Skipping.", product_id_str)
        return len(listings)
    median_price = float(np.median(prices))

    # Build feature matrix
    matrix = build_feature_matrix(listings, median_price, price_histories)
    if matrix.shape[0] < settings.min_listings_for_iforest:
        return matrix.shape[0]

    # Fit scaler
    scaled_matrix, scaler = fit_scaler(matrix)

    # Fit Isolation Forest
    effective_contamination = contamination or settings.if_contamination
    model = IsolationForest(
        n_estimators=settings.if_n_estimators,
        max_samples=settings.if_max_samples,
        contamination=effective_contamination,
        random_state=settings.if_random_state,
        n_jobs=-1,
    )
    model.fit(scaled_matrix)

    # Cache in Redis
    if _redis:
        model_bytes = pickle.dumps(model)
        scaler_bytes = pickle.dumps(scaler)
        # Also store group statistics for anomaly type derivation
        stats = {
            "mean": matrix.mean(axis=0).tobytes(),
            "std": matrix.std(axis=0).tobytes(),
            "median_price": median_price,
            "n_listings": len(listings),
        }
        stats_bytes = pickle.dumps(stats)

        pipe = _redis.pipeline()
        pipe.set(_model_key(product_id_str), model_bytes, ex=settings.model_cache_ttl_seconds)
        pipe.set(_scaler_key(product_id_str), scaler_bytes, ex=settings.model_cache_ttl_seconds)
        pipe.set(f"iforest:stats:{product_id_str}", stats_bytes, ex=settings.model_cache_ttl_seconds)
        await pipe.execute()

    logger.info(
        "Trained IF for product %s: %d listings, contamination=%.2f",
        product_id_str,
        len(listings),
        effective_contamination,
    )
    return len(listings)


# ── Scoring ──────────────────────────────────────────────────────────────


async def score_listing(item_id: str) -> AnomalyResult | None:
    """Score a single listing for price anomaly.

    Implements the fallback chain:
        N >= 5  → Isolation Forest (8 features)
        3 <= N < 5 → Z-score (price only)
        N < 3   → LLM overpay_ratio passthrough
    """
    # Resolve product info
    product_info = await fetch_product_by_item_id(item_id)
    if not product_info:
        logger.warning("Listing %s not found in DB.", item_id)
        return None

    product_id = product_info.get("product_id")
    if not product_id:
        logger.info("Listing %s has no linked product. Cannot score.", item_id)
        return None

    product_id_str = str(product_id)
    listings_count = int(product_info.get("listings_count") or 0)
    contamination = float(product_info.get("contamination") or settings.if_contamination)

    # Fetch all listings for this product
    listings = await fetch_listings_for_product(product_id)
    n = len(listings)

    # Find the target listing
    target = None
    for l in listings:
        if l.get("item_id") == item_id:
            target = l
            break

    if target is None:
        logger.warning("Listing %s not found in product group %s", item_id, product_id_str)
        return None

    prices = [float(l["price"]) for l in listings if l["price"] and float(l["price"]) > 0]
    median_price = float(np.median(prices)) if prices else 0.0
    target_price = float(target.get("price", 0))

    # ── Fallback: N < 3 → LLM overpay_ratio ──────────────────────────
    if n < settings.min_listings_for_zscore:
        meta = target.get("raw_metadata") or {}
        overpay = _safe_float(_extract_from_metadata(meta, "context", "overpay_ratio"), 0.0)
        return AnomalyResult(
            item_id=item_id,
            product_id=product_id_str,
            anomaly_score=overpay,
            is_anomaly=abs(overpay) > 0.3,
            anomaly_type="overpriced" if overpay > 0.3 else ("underpriced" if overpay < -0.3 else None),
            features={"overpay_ratio": overpay},
            confidence="insufficient",
            product_median_price=median_price,
            product_listing_count=n,
            method="llm_fallback",
        )

    # ── Fallback: 3 ≤ N < 5 → Z-score ────────────────────────────────
    if n < settings.min_listings_for_iforest:
        z = compute_zscore_price_only(prices, target_price)
        is_anomaly = abs(z) > 2.0
        if z < -2.0:
            atype = "underpriced"
        elif z > 2.0:
            atype = "overpriced"
        else:
            atype = None
        return AnomalyResult(
            item_id=item_id,
            product_id=product_id_str,
            anomaly_score=float(z),
            is_anomaly=is_anomaly,
            anomaly_type=atype,
            features={"price_zscore": float(z)},
            confidence="low",
            product_median_price=median_price,
            product_listing_count=n,
            method="zscore",
        )

    # ── Full Isolation Forest ─────────────────────────────────────────
    # Try to load cached model
    model: IsolationForest | None = None
    scaler = None
    stats: dict | None = None

    if _redis:
        model_bytes = await _redis.get(_model_key(product_id_str))
        scaler_bytes = await _redis.get(_scaler_key(product_id_str))
        stats_bytes = await _redis.get(f"iforest:stats:{product_id_str}")

        if model_bytes and scaler_bytes:
            model = pickle.loads(model_bytes)
            scaler = pickle.loads(scaler_bytes)
        if stats_bytes:
            stats = pickle.loads(stats_bytes)

    # If no cached model, train on the fly
    if model is None or scaler is None:
        logger.info("No cached model for product %s. Training on-demand.", product_id_str)
        await train_model_for_product(product_id, contamination)

        # Reload from cache
        if _redis:
            model_bytes = await _redis.get(_model_key(product_id_str))
            scaler_bytes = await _redis.get(_scaler_key(product_id_str))
            stats_bytes = await _redis.get(f"iforest:stats:{product_id_str}")
            if model_bytes and scaler_bytes:
                model = pickle.loads(model_bytes)
                scaler = pickle.loads(scaler_bytes)
            if stats_bytes:
                stats = pickle.loads(stats_bytes)

    if model is None or scaler is None:
        logger.error("Failed to train/load model for product %s", product_id_str)
        return None

    # Build feature vector for the target listing
    target_history = await fetch_price_history(target["listing_id"])
    from app.features.engineering import extract_features_for_listing

    feature_vector = extract_features_for_listing(target, median_price, target_history)
    scaled_vector = transform_with_scaler(feature_vector.reshape(1, -1), scaler)

    # Predict
    prediction = model.predict(scaled_vector)[0]  # 1 = normal, -1 = anomaly
    decision_score = float(model.decision_function(scaled_vector)[0])
    is_anomaly = prediction == -1

    # Determine anomaly type from feature analysis
    anomaly_type = None
    if is_anomaly and stats:
        group_mean = np.frombuffer(stats["mean"], dtype=np.float64)
        group_std = np.frombuffer(stats["std"], dtype=np.float64)
        anomaly_type = _derive_anomaly_type(feature_vector, group_mean, group_std)

    # Build feature dict for transparency
    features_dict = {name: float(feature_vector[i]) for i, name in enumerate(FEATURE_NAMES)}

    confidence = "high" if n >= 10 else "medium"

    return AnomalyResult(
        item_id=item_id,
        product_id=product_id_str,
        anomaly_score=decision_score,
        is_anomaly=is_anomaly,
        anomaly_type=anomaly_type,
        features=features_dict,
        confidence=confidence,
        product_median_price=median_price,
        product_listing_count=n,
        method="isolation_forest",
    )


async def score_product_batch(product_id: UUID | str) -> list[AnomalyResult]:
    """Score all active listings for a product in one batch.

    More efficient than individual scoring because we train once and
    predict for all listings simultaneously.
    """
    product_id_str = str(product_id)
    listings = await fetch_listings_for_product(product_id)
    n = len(listings)

    if n == 0:
        return []

    prices = [float(l["price"]) for l in listings if l["price"] and float(l["price"]) > 0]
    median_price = float(np.median(prices)) if prices else 0.0

    results: list[AnomalyResult] = []

    # For small groups, use simpler methods
    if n < settings.min_listings_for_zscore:
        for listing in listings:
            meta = listing.get("raw_metadata") or {}
            overpay = _safe_float(_extract_from_metadata(meta, "context", "overpay_ratio"), 0.0)
            results.append(AnomalyResult(
                item_id=listing["item_id"],
                product_id=product_id_str,
                anomaly_score=overpay,
                is_anomaly=abs(overpay) > 0.3,
                anomaly_type="overpriced" if overpay > 0.3 else ("underpriced" if overpay < -0.3 else None),
                features={"overpay_ratio": overpay},
                confidence="insufficient",
                product_median_price=median_price,
                product_listing_count=n,
                method="llm_fallback",
            ))
        return results

    if n < settings.min_listings_for_iforest:
        for listing in listings:
            target_price = float(listing.get("price", 0))
            z = compute_zscore_price_only(prices, target_price)
            is_anom = abs(z) > 2.0
            atype = "underpriced" if z < -2.0 else ("overpriced" if z > 2.0 else None)
            results.append(AnomalyResult(
                item_id=listing["item_id"],
                product_id=product_id_str,
                anomaly_score=float(z),
                is_anomaly=is_anom,
                anomaly_type=atype,
                features={"price_zscore": float(z)},
                confidence="low",
                product_median_price=median_price,
                product_listing_count=n,
                method="zscore",
            ))
        return results

    # ── Full IF batch ─────────────────────────────────────────────────
    # Gather price histories
    price_histories: dict[str, list[float]] = {}
    for listing in listings:
        lid = str(listing["listing_id"])
        price_histories[lid] = await fetch_price_history(listing["listing_id"])

    matrix = build_feature_matrix(listings, median_price, price_histories)
    scaled_matrix, scaler = fit_scaler(matrix)

    # Load or train model
    model: IsolationForest | None = None
    stats: dict | None = None

    # Fetch per-category contamination
    contamination = settings.if_contamination
    if listings:
        product_info = await fetch_product_by_item_id(listings[0]["item_id"])
        if product_info:
            contamination = float(product_info.get("contamination") or contamination)

    # Train fresh for batch (always most up-to-date)
    model = IsolationForest(
        n_estimators=settings.if_n_estimators,
        max_samples=settings.if_max_samples,
        contamination=contamination,
        random_state=settings.if_random_state,
        n_jobs=-1,
    )
    model.fit(scaled_matrix)

    # Cache the model
    if _redis:
        pipe = _redis.pipeline()
        pipe.set(_model_key(product_id_str), pickle.dumps(model), ex=settings.model_cache_ttl_seconds)
        pipe.set(_scaler_key(product_id_str), pickle.dumps(scaler), ex=settings.model_cache_ttl_seconds)
        stats_data = {
            "mean": matrix.mean(axis=0).tobytes(),
            "std": matrix.std(axis=0).tobytes(),
            "median_price": median_price,
            "n_listings": n,
        }
        pipe.set(f"iforest:stats:{product_id_str}", pickle.dumps(stats_data), ex=settings.model_cache_ttl_seconds)
        await pipe.execute()
        stats = stats_data

    # Predict all
    predictions = model.predict(scaled_matrix)
    scores = model.decision_function(scaled_matrix)

    group_mean = matrix.mean(axis=0)
    group_std = matrix.std(axis=0)
    confidence = "high" if n >= 10 else "medium"

    for i, listing in enumerate(listings):
        is_anomaly = predictions[i] == -1
        anomaly_type = None
        if is_anomaly:
            anomaly_type = _derive_anomaly_type(matrix[i], group_mean, group_std)

        features_dict = {name: float(matrix[i][j]) for j, name in enumerate(FEATURE_NAMES)}

        results.append(AnomalyResult(
            item_id=listing["item_id"],
            product_id=product_id_str,
            anomaly_score=float(scores[i]),
            is_anomaly=is_anomaly,
            anomaly_type=anomaly_type,
            features=features_dict,
            confidence=confidence,
            product_median_price=median_price,
            product_listing_count=n,
            method="isolation_forest",
        ))

    return results
