from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ml_service_listing.domain.models import Listing, ScoreResult
from ml_service_listing.domain.normalization import clamp
from ml_service_listing.domain.rules import evaluate_rules
from ml_service_listing.features.extractor import extract_features
from ml_service_listing.features.transformers import to_feature_row
from ml_service_listing.inference.predictor import (
    TrustScorePredictor,
    build_reasons,
    compute_confidence,
)
from ml_service_listing.training.model import load_model


class ModelTrustScorePredictor:
    """Predict trust scores using a trained model with rule-based fallback."""

    def __init__(self, model_path: str, logger: logging.Logger) -> None:
        self._model_path = Path(model_path)
        self._logger = logger
        self._fallback = TrustScorePredictor(logger)
        self._model = None
        self._model_mtime: float | None = None

    def predict_listing_with_source(self, listing: Listing) -> tuple[ScoreResult, bool]:
        model = self._get_model()
        if model is None:
            return self._fallback.predict_listing(listing), False

        features = extract_features(listing)
        row = to_feature_row(features)
        frame = pd.DataFrame([row])

        try:
            prediction = float(model.predict(frame)[0])
        except Exception as exc:
            self._logger.error(
                "model_prediction_failed",
                extra={
                    "event": "model_prediction_failed",
                    "listing_id": listing.listing_id,
                    "error": str(exc),
                },
            )
            return self._fallback.predict_listing(listing), False

        trust_score = clamp(prediction, 1.0, 10.0)
        confidence = compute_confidence(features)
        rule_outcome = evaluate_rules(listing, features)
        reasons = build_reasons(listing, features, rule_outcome.reasons)

        self._logger.info(
            "ml_scoring_decision",
            extra={
                "event": "ml_scoring_decision",
                "listing_id": listing.listing_id,
                "trust_score": trust_score,
                "confidence": confidence,
            },
        )

        return (
            ScoreResult(
                listing_id=listing.listing_id,
                trust_score=trust_score,
                confidence=confidence,
                reasons=reasons,
            ),
            True,
        )

    def predict_listing(self, listing: Listing) -> ScoreResult:
        result, _ = self.predict_listing_with_source(listing)
        return result

    def _get_model(self):
        if not self._model_path.exists():
            return None

        mtime = self._model_path.stat().st_mtime
        if self._model is None or self._model_mtime != mtime:
            model = load_model(str(self._model_path))
            self._model = model
            self._model_mtime = mtime
        return self._model
