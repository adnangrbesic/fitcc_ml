from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

from ml_service_listing.config.logging import configure_logging
from ml_service_listing.domain.models import Listing
from ml_service_listing.features.transformers import get_categorical_feature_names
from ml_service_listing.features.validators import validate_listing_data
from ml_service_listing.inference.predictor import TrustScorePredictor
from ml_service_listing.training.dataset import build_dataset
from ml_service_listing.training.label_generator import generate_labels
from ml_service_listing.training.metrics import compute_regression_metrics
from ml_service_listing.training.model import save_model, train_catboost_regressor


def _load_listing_json(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("listings", "items", "data"):
            if isinstance(data.get(key), list):
                return data[key]

    raise ValueError("Unsupported JSON structure for listings")


def _split_dataset(dataset, eval_split: float, seed: int):
    if eval_split <= 0:
        return dataset, None

    if not 0 < eval_split < 1:
        raise ValueError("eval-split must be between 0 and 1")

    total_rows = len(dataset)
    if total_rows < 5:
        return dataset, None

    indices = np.arange(total_rows)
    rng = np.random.default_rng(seed)
    rng.shuffle(indices)
    split_index = int(total_rows * (1 - eval_split))
    if split_index <= 0 or split_index >= total_rows:
        return dataset, None

    train_idx = indices[:split_index]
    eval_idx = indices[split_index:]
    train_df = dataset.iloc[train_idx].reset_index(drop=True)
    eval_df = dataset.iloc[eval_idx].reset_index(drop=True)
    return train_df, eval_df


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a trust score model")
    parser.add_argument("--input", required=True, help="Path to JSON listings")
    parser.add_argument("--output", required=True, help="Path to save model")
    parser.add_argument(
        "--use-generated-labels",
        action="store_true",
        help="Generate labels from rule-based scoring",
    )
    parser.add_argument(
        "--eval-split",
        type=float,
        default=0.2,
        help="Fraction of data to hold out for evaluation",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--metrics-out",
        default=None,
        help="Optional path to write evaluation metrics as JSON",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    configure_logging(args.log_level)
    logger = logging.getLogger("ml_service_listing.training")

    listing_items = _load_listing_json(Path(args.input))

    listings: list[Listing] = []
    labels: list[float] = []
    missing_labels = 0
    used_generated_labels = False

    for item in listing_items:
        listing = Listing.from_json(item)
        is_valid, errors = validate_listing_data(listing)
        if not is_valid:
            logger.warning(
                "training_listing_skipped",
                extra={
                    "event": "training_listing_skipped",
                    "listing_id": listing.listing_id,
                    "errors": errors,
                },
            )
            continue

        label = item.get("trustScore", item.get("trust_score"))
        if label is None:
            missing_labels += 1
        else:
            try:
                labels.append(float(label))
            except (TypeError, ValueError):
                missing_labels += 1
        listings.append(listing)

    if missing_labels > 0:
        if not args.use_generated_labels:
            raise ValueError("Missing labels. Use --use-generated-labels to fill them.")
        predictor = TrustScorePredictor(logger)
        labels = generate_labels(listings, predictor)
        used_generated_labels = True

    dataset = build_dataset(listings, labels)
    cat_features = get_categorical_feature_names()

    train_df, eval_df = _split_dataset(dataset, args.eval_split, args.seed)
    model = train_catboost_regressor(train_df, "trust_score", cat_features)
    save_model(model, args.output)

    if eval_df is not None:
        eval_X = eval_df.drop(columns=["trust_score"])
        eval_y = eval_df["trust_score"].to_numpy(dtype=float)
        preds = model.predict(eval_X)
        preds = np.clip(preds, 1.0, 10.0)
        metrics = compute_regression_metrics(eval_y, preds)

        logger.info(
            "evaluation_complete",
            extra={
                "event": "evaluation_complete",
                "rows_eval": len(eval_df),
                "metrics": metrics,
                "used_generated_labels": used_generated_labels,
            },
        )

        if args.metrics_out:
            with Path(args.metrics_out).open("w", encoding="utf-8") as handle:
                json.dump(metrics, handle, indent=2)

    logger.info(
        "training_complete",
        extra={
            "event": "training_complete",
            "rows": len(dataset),
            "rows_train": len(train_df),
            "rows_eval": 0 if eval_df is None else len(eval_df),
            "used_generated_labels": used_generated_labels,
        },
    )


if __name__ == "__main__":
    main()
