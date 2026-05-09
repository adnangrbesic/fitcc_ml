from __future__ import annotations

import logging
from typing import Any

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel

from ml_service_listing.config.logging import configure_logging
from ml_service_listing.config.settings import load_settings
from ml_service_listing.domain.models import Listing
from ml_service_listing.inference.model_predictor import ModelTrustScorePredictor
from ml_service_listing.training.retrainer import (
    append_listing_with_label,
    get_training_data_count,
    retrain_full,
    retrain_incremental,
)


class PredictRequest(BaseModel):
    listing: dict[str, Any]
    label: float | None = None
    retrain: bool | None = None


class PredictResponse(BaseModel):
    listing_id: str | int
    trust_score: float
    confidence: float
    reasons: list[str]
    model_used: bool


class HealthResponse(BaseModel):
    status: str
    model_path: str


class RetrainFullResponse(BaseModel):
    status: str
    rows: int
    model_path: str


load_dotenv()
_settings = load_settings()
configure_logging(_settings.log_level)
_logger = logging.getLogger("ml_service_listing.api")
_predictor = ModelTrustScorePredictor(_settings.model_path, _logger)

app = FastAPI(
    title="Trust Score Service",
    description="Predict trust scores for marketplace listings",
    version="0.1.0",
)


@app.get("/api/trust-score/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", model_path=_settings.model_path)


@app.post("/api/trust-score/predict", response_model=PredictResponse)
async def predict_trust_score(
    request: PredictRequest,
    background_tasks: BackgroundTasks,
) -> PredictResponse:
    if not isinstance(request.listing, dict):
        raise HTTPException(status_code=400, detail="listing payload must be an object")

    listing = Listing.from_json(request.listing)
    if listing.listing_id in (None, ""):
        raise HTTPException(status_code=400, detail="listing id is required")

    result, model_used = _predictor.predict_listing_with_source(listing)

    retrain_requested = request.retrain
    if retrain_requested is None:
        retrain_requested = _settings.retrain_enabled

    if retrain_requested:
        label = request.label if request.label is not None else result.trust_score
        background_tasks.add_task(
            _retrain_after_request,
            request.listing,
            float(label),
        )

    return PredictResponse(
        listing_id=result.listing_id,
        trust_score=result.trust_score,
        confidence=result.confidence,
        reasons=result.reasons,
        model_used=model_used,
    )


@app.post("/api/trust-score/retrain-full", response_model=RetrainFullResponse, status_code=202)
async def retrain_full_model(background_tasks: BackgroundTasks) -> RetrainFullResponse:
    rows = get_training_data_count(_settings.training_data_path)
    if rows == 0:
        raise HTTPException(status_code=400, detail="training dataset is empty")

    background_tasks.add_task(_retrain_full_task)
    return RetrainFullResponse(
        status="started",
        rows=rows,
        model_path=_settings.model_path,
    )


def _retrain_after_request(listing_payload: dict[str, Any], trust_score: float) -> None:
    try:
        append_listing_with_label(
            _settings.training_data_path,
            listing_payload,
            trust_score,
        )
        retrain_incremental(
            data_path=_settings.training_data_path,
            model_path=_settings.model_path,
            retrain_iterations=_settings.retrain_iterations,
            logger=_logger,
        )
    except Exception as exc:
        _logger.error(
            "retrain_failed",
            extra={"event": "retrain_failed", "error": str(exc)},
        )


def _retrain_full_task() -> None:
    try:
        retrain_full(
            data_path=_settings.training_data_path,
            model_path=_settings.model_path,
            logger=_logger,
        )
    except Exception as exc:
        _logger.error(
            "retrain_full_failed",
            extra={"event": "retrain_full_failed", "error": str(exc)},
        )
