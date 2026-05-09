from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ml_service_listing.domain.models import Listing
from ml_service_listing.features.validators import (
    manufacturer_mismatch,
    missing_critical_specs,
    suspicious_price,
    title_spec_consistency,
)


@dataclass(frozen=True)
class FeatureSet:
    numeric: dict[str, float | None]
    boolean: dict[str, bool | None]
    categorical: dict[str, str | None]
    derived: dict[str, bool | None]


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "."))
        except ValueError:
            return None
    return None


def _to_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "on"}:
            return True
        if lowered in {"false", "0", "no", "n", "off"}:
            return False
    return None


def _get_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def extract_features(listing: Listing) -> FeatureSet:
    raw = listing.raw_metadata or {}
    title_meta = _get_dict(raw.get("title"))
    context = _get_dict(raw.get("context"))
    attributes = _get_dict(raw.get("attributes"))
    raw_specs = _get_dict(raw.get("raw_specs"))

    numeric = {
        "condition": _to_float(context.get("condition")),
        "overpay_ratio": _to_float(context.get("overpay_ratio")),
        "warranty_months": _to_float(context.get("warranty_months")),
        "writing_quality": _to_float(context.get("writing_quality")),
        "title_score": _to_float(title_meta.get("score")),
        "canonical_confidence": _to_float(title_meta.get("canonical_confidence")),
        "ram_gb": _to_float(attributes.get("ram_gb")),
        "storage_gb": _to_float(attributes.get("storage_gb")),
        "battery_health_percent": _to_float(attributes.get("battery_health_percent")),
    }

    boolean = {
        "is_for_parts": _to_bool(attributes.get("is_for_parts")),
        "is_global_version": _to_bool(attributes.get("is_global_version")),
        "has_face_id_or_touch_id_issue": _to_bool(
            attributes.get("has_face_id_or_touch_id_issue")
        ),
    }

    raw_manufacturer = raw_specs.get("manufacturer")
    if raw_manufacturer is None:
        raw_manufacturer = attributes.get("manufacturer")

    categorical = {
        "category": raw.get("category"),
        "breadcrumbs": raw.get("breadcrumbs"),
        "canonical_name": title_meta.get("canonical_name"),
        "raw_manufacturer": raw_manufacturer,
    }

    derived = {
        "manufacturer_mismatch": manufacturer_mismatch(
            raw_manufacturer=categorical["raw_manufacturer"],
            canonical_name=categorical["canonical_name"],
            title=listing.title,
        ),
        "title_spec_consistency": title_spec_consistency(
            title=listing.title,
            storage_gb=numeric["storage_gb"],
        ),
        "suspicious_price": suspicious_price(numeric["overpay_ratio"]),
        "missing_critical_specs": missing_critical_specs(
            category=categorical["category"],
            storage_gb=numeric["storage_gb"],
            ram_gb=numeric["ram_gb"],
        ),
    }

    return FeatureSet(
        numeric=numeric,
        boolean=boolean,
        categorical=categorical,
        derived=derived,
    )
