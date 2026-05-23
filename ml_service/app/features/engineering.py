# ---------------------------------------------------------------------------
# BuyGuardian ML Service — Feature Engineering
# ---------------------------------------------------------------------------
"""Extract and normalize the 8-dimensional feature matrix for Isolation Forest.

Features (per listing, within a product group):
    1. Relative Price Deviation  — (price - median) / median
    2. Condition-to-Price Ratio  — condition / normalized_price
    3. Warranty Weight           — proportional scale min(m/6, 1.0) for warranty months
    4. Seller Reliability Anchor — log1p(deliveries) * log1p(age_months)
    5. Price Volatility          — std(price_history) / median
    6. Listing Staleness         — days since first scraped
    7. Negative Feedback Ratio   — negative / (positive + 1)
    8. Description Spam Score    — caps_ratio*0.5 + min(excl/10,1)*0.5
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

import numpy as np
from sklearn.preprocessing import RobustScaler

logger = logging.getLogger(__name__)

# Feature column names in order
FEATURE_NAMES: list[str] = [
    "price_deviation",
    "condition_to_price",
    "warranty_weight",
    "seller_reliability",
    "price_volatility",
    "listing_staleness",
    "negative_feedback_ratio",
    "spam_score",
]


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Safely cast a value to float."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    """Safely cast a value to int."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _extract_from_metadata(raw_metadata: dict | None, *keys: str, default: Any = None) -> Any:
    """Navigate nested dict keys safely.

    Example: _extract_from_metadata(meta, "context", "condition") → 0.85
    """
    if not raw_metadata:
        return default
    current = raw_metadata
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return default
        if current is None:
            return default
    return current


def extract_features_for_listing(
    listing: dict[str, Any],
    median_price: float,
    price_history: list[float],
) -> np.ndarray:
    """Build a single feature vector (1×8) for one listing.

    Args:
        listing: Dict with columns from the DB query (see db.py).
        median_price: Median price across all active listings for this product.
        price_history: Price history for this specific listing.

    Returns:
        1-D numpy array of shape (8,).
    """
    price = _safe_float(listing.get("price"), 0.0)
    meta = listing.get("raw_metadata") or {}

    # ── Feature 1: Relative Price Deviation ───────────────────────────────
    if median_price > 0:
        price_deviation = (price - median_price) / median_price
    else:
        price_deviation = 0.0

    # ── Feature 2: Condition-to-Price Ratio ───────────────────────────────
    condition = _safe_float(_extract_from_metadata(meta, "context", "condition"), 0.5)
    normalized_price = price / median_price if median_price > 0 else 1.0
    # Avoid division by zero for normalized_price
    condition_to_price = condition / max(normalized_price, 0.01)

    # ── Feature 3: Warranty Weight (proportional, 0–1 scale) ────────────
    # A listing with 12+ months warranty gets max weight of 1.0.
    # Scales proportionally so that longer warranties (e.g. 24 months)
    # aren't unfairly penalized vs. 1-month "warranties".
    warranty_months = _safe_int(_extract_from_metadata(meta, "context", "warranty_months"), 0)
    warranty_weight = min(float(warranty_months) / 6.0, 1.0) if warranty_months > 0 else 0.0

    # ── Feature 4: Seller Reliability Anchor ──────────────────────────────
    deliveries = _safe_int(listing.get("successful_deliveries"), 0)
    age_months = _safe_int(listing.get("account_age_months"), 0)
    seller_reliability = math.log1p(deliveries) * math.log1p(age_months)

    # ── Feature 5: Price Volatility ───────────────────────────────────────
    if len(price_history) >= 2 and median_price > 0:
        price_volatility = float(np.std(price_history)) / median_price
    else:
        price_volatility = 0.0

    # ── Feature 6: Listing Staleness (days) ───────────────────────────────
    scraped_at = listing.get("scraped_at")
    if scraped_at:
        if isinstance(scraped_at, datetime):
            if scraped_at.tzinfo is None:
                scraped_at = scraped_at.replace(tzinfo=timezone.utc)
            staleness = (datetime.now(timezone.utc) - scraped_at).days
        else:
            staleness = 0
    else:
        staleness = 0
    listing_staleness = float(max(staleness, 0))

    # ── Feature 7: Negative Feedback Ratio ────────────────────────────────
    negative = _safe_int(listing.get("negative_feedback"), 0)
    positive = _safe_int(listing.get("positive_feedback"), 0)
    negative_feedback_ratio = negative / (positive + 1)

    # ── Feature 8: Description Spam Score ─────────────────────────────────
    caps_ratio = _safe_float(_extract_from_metadata(meta, "description_caps_ratio"), 0.0)
    excl_count = _safe_int(_extract_from_metadata(meta, "description_exclamation_count"), 0)
    spam_score = caps_ratio * 0.5 + min(excl_count / 10.0, 1.0) * 0.5

    return np.array(
        [
            price_deviation,
            condition_to_price,
            warranty_weight,
            seller_reliability,
            price_volatility,
            listing_staleness,
            negative_feedback_ratio,
            spam_score,
        ],
        dtype=np.float64,
    )


def build_feature_matrix(
    listings: list[dict[str, Any]],
    median_price: float,
    price_histories: dict[str, list[float]],
) -> np.ndarray:
    """Build the full feature matrix (N×8) for a product group.

    Args:
        listings: List of listing dicts from DB.
        median_price: Median price for this product.
        price_histories: Mapping of listing_id → price history list.

    Returns:
        2-D numpy array of shape (N, 8).
    """
    rows: list[np.ndarray] = []
    for listing in listings:
        lid = str(listing.get("listing_id", ""))
        history = price_histories.get(lid, [])
        row = extract_features_for_listing(listing, median_price, history)
        rows.append(row)

    if not rows:
        return np.empty((0, len(FEATURE_NAMES)))

    return np.vstack(rows)


def fit_scaler(matrix: np.ndarray) -> tuple[np.ndarray, RobustScaler]:
    """Fit a RobustScaler on the feature matrix and return scaled data + scaler.

    Uses quantile_range=(10, 90) to be resilient against extreme outliers
    like 1 KM placeholders or 999999 KM trolls.
    """
    scaler = RobustScaler(quantile_range=(10.0, 90.0))
    scaled = scaler.fit_transform(matrix)
    return scaled, scaler


def transform_with_scaler(matrix: np.ndarray, scaler: RobustScaler) -> np.ndarray:
    """Apply a previously fitted scaler to new data."""
    return scaler.transform(matrix)


def compute_zscore_price_only(prices: list[float], target_price: float) -> float:
    """Simple Z-score fallback for groups with 3 ≤ N < 5.

    Returns the Z-score of `target_price` relative to the price distribution.
    """
    if len(prices) < 2:
        return 0.0
    mean = float(np.mean(prices))
    std = float(np.std(prices, ddof=1))
    if std < 1e-9:
        return 0.0
    return (target_price - mean) / std
