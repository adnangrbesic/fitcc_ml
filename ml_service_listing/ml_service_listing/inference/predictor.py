"""
Trust score prediction pipeline.

TrustScorePredictor: rule-based fallback predictor.
  - Extracts features from listing metadata
  - Evaluates business rules (for-parts, mismatch, suspicious price)
  - Computes subscores and composite
  - Returns ScoreResult with confidence and reasons

compute_confidence: weighted by data source reliability.
  - Scraped data (condition, warranty, specs): weight 0.85–0.90
  - LLM-derived (overpay_ratio, writing_quality): weight 0.50–0.55
  - Heuristic (title_score, canonical_confidence): weight 0.65–0.70
"""
from __future__ import annotations

import logging

from ml_service_listing.domain.models import Listing, ScoreResult
from ml_service_listing.domain.normalization import to_trust_score
from ml_service_listing.domain.rules import evaluate_rules
from ml_service_listing.domain.scoring import (
    apply_rule_outcome,
    compute_composite_score,
    compute_subscores,
)
from ml_service_listing.features.extractor import FeatureSet, extract_features


class TrustScorePredictor:
    """Compute trust scores for listings using rules and a composite formula.
    
    This is the rule-based fallback when CatBoost model is unavailable
    or when prediction fails. It uses deterministic business rules.
    """

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def predict_listing(self, listing: Listing) -> ScoreResult:
        """Full prediction pipeline: features → rules → subscores → composite → trust score."""
        features = extract_features(listing)
        rule_outcome = evaluate_rules(listing, features)
        subscores = compute_subscores(listing, features)
        composite = compute_composite_score(subscores)
        adjusted = apply_rule_outcome(composite, rule_outcome)
        trust_score = to_trust_score(adjusted)
        confidence = compute_confidence(features)
        reasons = build_reasons(listing, features, rule_outcome.reasons)

        self._logger.info(
            "scoring_decision",
            extra={
                "event": "scoring_decision",
                "listing_id": listing.listing_id,
                "trust_score": trust_score,
                "confidence": confidence,
            },
        )

        return ScoreResult(
            listing_id=listing.listing_id,
            trust_score=trust_score,
            confidence=confidence,
            reasons=reasons,
        )


def compute_confidence(features: FeatureSet) -> float:
    """Compute confidence based on data completeness AND source reliability.

    Different features have different reliability:
      - Scraped data (condition, warranty, RAM, storage) = high confidence
      - LLM-derived (overpay_ratio, writing_quality) = medium confidence
      - Derived/heuristic (title_score, canonical_confidence) = medium-low
    """
    # Each feature: (value_present, reliability_weight 0-1)
    feature_weights = [
        (features.numeric.get("condition"), 0.90),        # scraped, very reliable
        (features.numeric.get("overpay_ratio"), 0.55),    # LLM approximation
        (features.numeric.get("warranty_months"), 0.85),  # scraped, reliable
        (features.numeric.get("writing_quality"), 0.50),  # LLM text analysis
        (features.numeric.get("title_score"), 0.70),      # heuristic match
        (features.numeric.get("canonical_confidence"), 0.65),  # NLP match
        (features.numeric.get("ram_gb"), 0.90),           # scraped spec
        (features.numeric.get("storage_gb"), 0.90),       # scraped spec
    ]

    total_weight = sum(w for _, w in feature_weights)
    present_weight = sum(w for val, w in feature_weights if val is not None)

    raw_confidence = present_weight / total_weight if total_weight > 0 else 0.0

    # Scale: 50% baseline + 50% from data quality
    confidence = round(0.5 + 0.5 * raw_confidence, 2)
    return max(0.1, min(0.99, confidence))


def build_reasons(
    listing: Listing,
    features: FeatureSet,
    rule_reasons: list[str],
) -> list[str]:
    reasons: list[str] = []
    reasons.extend(rule_reasons)

    warranty_months = features.numeric.get("warranty_months")
    if warranty_months is not None and warranty_months >= 3:
        reasons.append("Warranty present")

    if listing.description:
        if len(listing.description) >= 120:
            reasons.append("Detailed description")
        elif len(listing.description) <= 20:
            reasons.append("Minimal description")

    writing_quality = features.numeric.get("writing_quality")
    if writing_quality is not None:
        if writing_quality >= 7:
            reasons.append("Clear writing")
        elif writing_quality <= 3:
            reasons.append("Poor writing quality")

    overpay_ratio = features.numeric.get("overpay_ratio")
    if overpay_ratio is not None:
        if overpay_ratio > 0.3:
            reasons.append("Overpriced vs market")
        elif overpay_ratio < -0.3:
            reasons.append("Below market price")

    if features.derived.get("missing_critical_specs") is True:
        reasons.append("Missing key specs")

    unique: list[str] = []
    for reason in reasons:
        if reason not in unique:
            unique.append(reason)
    return unique[:5]
