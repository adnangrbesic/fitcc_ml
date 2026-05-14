from __future__ import annotations

from dataclasses import dataclass, field

from ml_service_listing.domain.models import Listing
from ml_service_listing.features.extractor import FeatureSet


@dataclass
class RuleOutcome:
    hard_fail: bool
    max_score: float | None
    penalty: float
    reasons: list[str] = field(default_factory=list)


def _min_score(current: float | None, candidate: float) -> float:
    if current is None:
        return candidate
    return min(current, candidate)


def evaluate_rules(listing: Listing, features: FeatureSet) -> RuleOutcome:
    reasons: list[str] = []
    penalty = 0.0
    max_score: float | None = None

    is_for_parts = features.boolean.get("is_for_parts")
    if is_for_parts is True:
        reasons.append("Listed for parts")
        penalty += 50.0
        max_score = _min_score(max_score, 20.0)

    manufacturer_mismatch = features.derived.get("manufacturer_mismatch")
    if manufacturer_mismatch is True:
        reasons.append("Manufacturer mismatch")
        penalty += 30.0

    overpay_ratio = features.numeric.get("overpay_ratio")
    suspicious_price = features.derived.get("suspicious_price")
    if suspicious_price is True and overpay_ratio is not None and overpay_ratio < -0.6:
        reasons.append("Suspiciously underpriced")
        penalty += 40.0
        max_score = _min_score(max_score, 30.0)

    title_spec_consistency = features.derived.get("title_spec_consistency")
    if title_spec_consistency is False:
        reasons.append("Spec mismatch between title and attributes")
        penalty += 25.0

    missing_specs = features.derived.get("missing_critical_specs")
    if missing_specs is True:
        reasons.append("Missing critical specs")
        penalty += 20.0

    if not listing.description or len(listing.description.strip()) < 15:
        reasons.append("Empty or very short description")
        penalty += 15.0

    hard_fail = max_score is not None and max_score <= 20.0
    return RuleOutcome(
        hard_fail=hard_fail,
        max_score=max_score,
        penalty=penalty,
        reasons=reasons,
    )
