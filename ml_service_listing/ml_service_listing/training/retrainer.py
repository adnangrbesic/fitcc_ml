from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import Lock
from typing import Any

from ml_service_listing.domain.models import Listing
from ml_service_listing.features.transformers import get_categorical_feature_names
from ml_service_listing.features.validators import validate_listing_data
from ml_service_listing.training.dataset import build_dataset
from ml_service_listing.training.model import continue_training, save_model, train_catboost_regressor


_DATA_LOCK = Lock()


def _load_listing_json(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("listings", "items", "data"):
            if isinstance(data.get(key), list):
                return data[key]

    return []


def append_listing_with_label(
    path: str,
    listing_payload: dict[str, Any],
    trust_score: float,
) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    with _DATA_LOCK:
        data = _load_listing_json(file_path)
        entry = dict(listing_payload)
        entry["trustScore"] = trust_score
        data.append(entry)

        with file_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=True, indent=2)


def retrain_incremental(
    data_path: str,
    model_path: str,
    retrain_iterations: int,
    logger: logging.Logger,
) -> None:
    file_path = Path(data_path)

    with _DATA_LOCK:
        data = _load_listing_json(file_path)

    if not data:
        logger.warning("retrain_skipped", extra={"event": "retrain_skipped", "reason": "no_data"})
        return

    listings: list[Listing] = []
    labels: list[float] = []

    for item in data:
        try:
            listing = Listing.from_json(item)
        except Exception as exc:
            logger.warning(
                "retrain_listing_parse_failed",
                extra={"event": "retrain_listing_parse_failed", "error": str(exc)},
            )
            continue

        is_valid, errors = validate_listing_data(listing)
        if not is_valid:
            logger.warning(
                "retrain_listing_invalid",
                extra={
                    "event": "retrain_listing_invalid",
                    "listing_id": listing.listing_id,
                    "errors": errors,
                },
            )
            continue

        label = item.get("trustScore", item.get("trust_score"))
        if label is None:
            continue
        try:
            labels.append(float(label))
        except (TypeError, ValueError):
            continue

        listings.append(listing)

    if not listings:
        logger.warning("retrain_skipped", extra={"event": "retrain_skipped", "reason": "no_valid_rows"})
        return

    dataset = build_dataset(listings, labels)
    cat_features = get_categorical_feature_names()

    continue_training(
        dataset=dataset,
        target_column="trust_score",
        cat_features=cat_features,
        model_path=model_path,
        iterations=retrain_iterations,
    )

    logger.info(
        "retrain_complete",
        extra={
            "event": "retrain_complete",
            "rows": len(dataset),
            "iterations": retrain_iterations,
        },
    )


def get_training_data_count(data_path: str) -> int:
    file_path = Path(data_path)
    with _DATA_LOCK:
        data = _load_listing_json(file_path)
    return len(data)


def retrain_full(
    data_path: str,
    model_path: str,
    logger: logging.Logger,
) -> int:
    file_path = Path(data_path)

    with _DATA_LOCK:
        data = _load_listing_json(file_path)

    if not data:
        logger.warning("retrain_full_skipped", extra={"event": "retrain_full_skipped", "reason": "no_data"})
        return 0

    listings: list[Listing] = []
    labels: list[float] = []

    for item in data:
        try:
            listing = Listing.from_json(item)
        except Exception as exc:
            logger.warning(
                "retrain_full_listing_parse_failed",
                extra={"event": "retrain_full_listing_parse_failed", "error": str(exc)},
            )
            continue

        is_valid, errors = validate_listing_data(listing)
        if not is_valid:
            logger.warning(
                "retrain_full_listing_invalid",
                extra={
                    "event": "retrain_full_listing_invalid",
                    "listing_id": listing.listing_id,
                    "errors": errors,
                },
            )
            continue

        label = item.get("trustScore", item.get("trust_score"))
        if label is None:
            continue
        try:
            labels.append(float(label))
        except (TypeError, ValueError):
            continue

        listings.append(listing)

    if not listings:
        logger.warning(
            "retrain_full_skipped",
            extra={"event": "retrain_full_skipped", "reason": "no_valid_rows"},
        )
        return 0

    dataset = build_dataset(listings, labels)
    cat_features = get_categorical_feature_names()
    model = train_catboost_regressor(
        dataset=dataset,
        target_column="trust_score",
        cat_features=cat_features,
    )
    save_model(model, model_path)

    logger.info(
        "retrain_full_complete",
        extra={
            "event": "retrain_full_complete",
            "rows": len(dataset),
        },
    )
    return len(dataset)
