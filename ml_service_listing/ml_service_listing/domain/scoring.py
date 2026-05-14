from __future__ import annotations

from ml_service_listing.domain.models import Listing, Subscores
from ml_service_listing.domain.normalization import normalize_0_100
from ml_service_listing.domain.rules import RuleOutcome
from ml_service_listing.features.extractor import FeatureSet


def compute_subscores(listing: Listing, features: FeatureSet) -> Subscores:
    seller_score = _seller_score(listing)
    consistency_score = _consistency_score(features)
    condition_score = _condition_score(listing, features)
    pricing_score = _pricing_score(features)
    writing_score = _writing_score(listing, features)
    return Subscores(
        seller_score=seller_score,
        consistency_score=consistency_score,
        condition_score=condition_score,
        pricing_score=pricing_score,
        writing_score=writing_score,
    )


def compute_composite_score(subscores: Subscores) -> float:
    return (
        0.30 * subscores.seller_score
        + 0.25 * subscores.consistency_score
        + 0.20 * subscores.condition_score
        + 0.15 * subscores.pricing_score
        + 0.10 * subscores.writing_score
    )


def apply_rule_outcome(score_0_100: float, rule_outcome: RuleOutcome) -> float:
    adjusted = score_0_100 - rule_outcome.penalty
    if rule_outcome.max_score is not None:
        adjusted = min(adjusted, rule_outcome.max_score)
    return normalize_0_100(adjusted)


def _seller_score(listing: Listing) -> float:
    context = listing.raw_metadata.get("context", {})
    overall = context.get("overall_listing_trust")
    if overall is not None:
        try:
            return normalize_0_100(float(overall) * 10.0)
        except (TypeError, ValueError):
            pass
    return 75.0


def _consistency_score(features: FeatureSet) -> float:
    score = 100.0
    if features.derived.get("manufacturer_mismatch") is True:
        score -= 25.0
    if features.derived.get("title_spec_consistency") is False:
        score -= 20.0
    if features.derived.get("missing_critical_specs") is True:
        score -= 20.0
    return normalize_0_100(score)


def _condition_score(listing: Listing, features: FeatureSet) -> float:
    condition = features.numeric.get("condition")
    if condition is not None:
        if 0.0 <= condition <= 1.0:
            return normalize_0_100(condition * 100.0)
        if 1.0 < condition <= 100.0:
            return normalize_0_100(condition)
    if listing.is_new is True:
        return 90.0
    return 60.0


def _pricing_score(features: FeatureSet) -> float:
    ratio = features.numeric.get("overpay_ratio")
    if ratio is None:
        return 75.0
    if ratio < -0.7:
        return 20.0
    if ratio < -0.5:
        return 50.0
    if ratio < -0.3:
        return 85.0
    if ratio < -0.1:
        return 95.0
    if ratio <= 0.2:
        return 95.0
    if ratio <= 0.5:
        return 80.0
    if ratio <= 1.0:
        return 60.0
    return 40.0


def _writing_score(listing: Listing, features: FeatureSet) -> float:
    writing_quality = features.numeric.get("writing_quality")
    if writing_quality is not None and writing_quality > 0:
        return normalize_0_100(writing_quality * 10.0)
    
    if not listing.description or len(listing.description.strip()) < 15:
        return 10.0
    if len(listing.description) > 200:
        return 80.0
    if len(listing.description) > 80:
        return 60.0
    return 30.0
