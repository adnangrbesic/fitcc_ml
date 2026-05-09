from __future__ import annotations

import logging
from typing import Iterable

from ml_service_listing.api.client import ApiClient
from ml_service_listing.config.settings import Settings
from ml_service_listing.domain.models import Listing, ScoreResult
from ml_service_listing.features.validators import validate_listing_data
from ml_service_listing.inference.predictor import TrustScorePredictor


class ScoringPipeline:
    """Fetch listings, score them, and submit results to the API."""

    def __init__(
        self,
        client: ApiClient,
        predictor: TrustScorePredictor,
        settings: Settings,
        logger: logging.Logger,
    ) -> None:
        self._client = client
        self._predictor = predictor
        self._settings = settings
        self._logger = logger

    def run_once(self, dry_run: bool = False) -> None:
        listings_data = self.fetch_unscored_listings()
        if not listings_data:
            self._logger.info("no_unscored_listings", extra={"event": "no_listings"})
            return

        results: list[ScoreResult] = []
        for item in listings_data:
            if not isinstance(item, dict):
                self._logger.warning(
                    "invalid_listing_payload",
                    extra={"event": "invalid_listing", "payload": str(item)},
                )
                continue
            try:
                listing = Listing.from_json(item)
            except Exception as exc:
                self._logger.warning(
                    "listing_parse_failed",
                    extra={"event": "listing_parse_failed", "error": str(exc)},
                )
                continue

            is_valid, errors = validate_listing_data(listing)
            if not is_valid:
                self._logger.warning(
                    "listing_validation_failed",
                    extra={
                        "event": "listing_validation_failed",
                        "listing_id": listing.listing_id,
                        "errors": errors,
                    },
                )
                continue

            try:
                result = self._predictor.predict_listing(listing)
                results.append(result)
            except Exception as exc:
                self._logger.error(
                    "scoring_failed",
                    extra={
                        "event": "scoring_failed",
                        "listing_id": listing.listing_id,
                        "error": str(exc),
                    },
                )

        if not results:
            self._logger.info("no_scored_results", extra={"event": "no_results"})
            return

        if dry_run:
            self._logger.info(
                "dry_run",
                extra={"event": "dry_run", "count": len(results)},
            )
            return

        self.submit_scores(results)

    def fetch_unscored_listings(self) -> list[dict[str, object]]:
        data = self._client.get_json(self._settings.unscored_endpoint)
        if not isinstance(data, list):
            self._logger.error(
                "unexpected_unscored_response",
                extra={"event": "unexpected_response", "type": str(type(data))},
            )
            return []
        return data

    def submit_scores(self, results: list[ScoreResult]) -> None:
        if not results:
            return

        mode = self._settings.score_payload_mode
        if mode == "batch":
            for chunk in _chunk(results, self._settings.batch_size):
                payload = {"scores": [result.as_payload() for result in chunk]}
                self._client.post_json(self._settings.score_endpoint, payload)
                self._logger.info(
                    "scores_submitted",
                    extra={"event": "scores_submitted", "count": len(chunk)},
                )
            return

        if mode == "map":
            for chunk in _chunk(results, self._settings.batch_size):
                payload = {
                    "score": {str(result.listing_id): result.trust_score for result in chunk}
                }
                self._client.post_json(self._settings.score_endpoint, payload)
                self._logger.info(
                    "scores_submitted",
                    extra={"event": "scores_submitted", "count": len(chunk)},
                )
            return

        for result in results:
            self._client.post_json(self._settings.score_endpoint, result.as_payload())
        self._logger.info(
            "scores_submitted",
            extra={"event": "scores_submitted", "count": len(results)},
        )


def _chunk(items: Iterable[ScoreResult], size: int) -> Iterable[list[ScoreResult]]:
    batch: list[ScoreResult] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
