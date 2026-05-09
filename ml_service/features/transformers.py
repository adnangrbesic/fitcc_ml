from __future__ import annotations

from ml_service_listing.features.extractor import FeatureSet


def to_feature_row(feature_set: FeatureSet) -> dict[str, object]:
    row: dict[str, object] = {}

    for key, value in feature_set.numeric.items():
        row[key] = value

    for key, value in feature_set.boolean.items():
        row[key] = int(value) if value is not None else None

    for key, value in feature_set.derived.items():
        row[key] = int(value) if value is not None else None

    for key, value in feature_set.categorical.items():
        row[key] = value or ""

    return row


def get_categorical_feature_names(feature_set: FeatureSet | None = None) -> list[str]:
    if feature_set is None:
        return ["category", "breadcrumbs", "canonical_name", "raw_manufacturer"]
    return list(feature_set.categorical.keys())
