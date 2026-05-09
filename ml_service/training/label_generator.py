from __future__ import annotations

import logging

from ml_service_listing.domain.models import Listing
from ml_service_listing.inference.predictor import TrustScorePredictor


def generate_labels(
    listings: list[Listing],
    predictor: TrustScorePredictor | None = None,
) -> list[float]:
    if predictor is None:
        predictor = TrustScorePredictor(logging.getLogger("ml_service_listing.training"))

    labels: list[float] = []
    for listing in listings:
        result = predictor.predict_listing(listing)
        labels.append(result.trust_score)
    return labels
