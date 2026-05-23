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


def retrain_full_from_entries(
    entries: list[dict[str, Any]],
    model_path: str,
    logger: logging.Logger,
) -> int:
    """Retrain from admin-labeled entries merged with rule-based labels.

    HYBRID APPROACH:
      1. Admin-labeled entries → ground truth (high weight)
      2. All other listings in the existing training dataset → rule-based labels (baseline)
      3. If a listing has both, admin label wins.

    This means the model always has a full dataset to train on, but your
    personal labels override the rules where you've reviewed a listing.
    """
    if not entries:
        logger.warning(
            "retrain_from_entries_skipped",
            extra={"event": "retrain_from_entries_skipped", "reason": "no_entries"},
        )
        return 0

    # ── Load existing training data (rule-based labels) ────────────────
    from ml_service_listing.config.settings import load_settings

    settings = load_settings()
    file_path = Path(settings.training_data_path)
    existing_data = _load_listing_json(file_path)

    # Build a set of itemIds that have admin labels (so we can replace them)
    admin_labeled_ids: set[str] = set()
    admin_entries_by_id: dict[str, dict[str, Any]] = {}
    for entry in entries:
        item_id = str(entry.get("itemId", entry.get("item_id", "")))
        if item_id:
            admin_labeled_ids.add(item_id)
            admin_entries_by_id[item_id] = entry

    # ── Merge: admin labels replace rule labels for overlapping listings ──
    merged: list[dict[str, Any]] = []

    # Add rule-based entries that don't have admin labels
    rules_kept = 0
    rules_replaced = 0
    for item in existing_data:
        item_id = str(item.get("itemId", item.get("item_id", "")))
        if item_id in admin_labeled_ids:
            # Admin label overrides — skip the rule-based version
            rules_replaced += 1
        else:
            merged.append(item)
            rules_kept += 1

    # Add all admin-labeled entries
    merged.extend(entries)

    # ── Build dataset from merged entries ──────────────────────────────
    listings: list[Listing] = []
    labels: list[float] = []

    for item in merged:
        try:
            listing = Listing.from_json(item)
        except Exception as exc:
            logger.warning(
                "retrain_entry_parse_failed",
                extra={"event": "retrain_entry_parse_failed", "error": str(exc)},
            )
            continue

        is_valid, errors = validate_listing_data(listing)
        if not is_valid:
            logger.warning(
                "retrain_entry_invalid",
                extra={
                    "event": "retrain_entry_invalid",
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
            "retrain_from_entries_skipped",
            extra={"event": "retrain_from_entries_skipped", "reason": "no_valid_rows"},
        )
        return 0

    # ── Train ──────────────────────────────────────────────────────────
    dataset = build_dataset(listings, labels)
    cat_features = get_categorical_feature_names()
    model = train_catboost_regressor(
        dataset=dataset,
        target_column="trust_score",
        cat_features=cat_features,
    )
    save_model(model, model_path)

    logger.info(
        "retrain_from_entries_complete",
        extra={
            "event": "retrain_from_entries_complete",
            "total_rows": len(dataset),
            "admin_labels": len(entries),
            "rule_labels_kept": rules_kept,
            "rule_labels_replaced": rules_replaced,
        },
    )
    return len(dataset)
