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
    """Compute trust scores for listings using rules and a composite formula."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def predict_listing(self, listing: Listing) -> ScoreResult:
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
    fields = [
        features.numeric.get("condition"),
        features.numeric.get("overpay_ratio"),
        features.numeric.get("warranty_months"),
        features.numeric.get("writing_quality"),
        features.numeric.get("title_score"),
        features.numeric.get("canonical_confidence"),
        features.numeric.get("ram_gb"),
        features.numeric.get("storage_gb"),
    ]
    present = sum(1 for value in fields if value is not None)
    ratio = present / len(fields)
    confidence = round(0.5 + 0.5 * ratio, 2)
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
