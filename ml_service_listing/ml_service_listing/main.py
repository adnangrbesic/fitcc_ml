from __future__ import annotations

import argparse
import logging
import time

from dotenv import load_dotenv

from ml_service_listing.api.client import ApiClient
from ml_service_listing.config.logging import configure_logging
from ml_service_listing.config.settings import load_settings
from ml_service_listing.inference.pipeline import ScoringPipeline
from ml_service_listing.inference.predictor import TrustScorePredictor


def main() -> None:
    load_dotenv()
    settings = load_settings()
    configure_logging(settings.log_level)

    logger = logging.getLogger("ml_service_listing")
    client = ApiClient(
        base_url=settings.api_base_url,
        api_key=settings.api_key,
        api_key_header=settings.api_key_header,
        timeout_seconds=settings.timeout_seconds,
        verify_ssl=settings.verify_ssl,
        logger=logger,
    )
    predictor = TrustScorePredictor(logger)
    pipeline = ScoringPipeline(client=client, predictor=predictor, settings=settings, logger=logger)

    parser = argparse.ArgumentParser(description="Trust score pipeline")
    parser.add_argument("--once", action="store_true", help="Run a single pass")
    parser.add_argument("--poll", action="store_true", help="Poll for listings")
    parser.add_argument(
        "--interval",
        type=float,
        default=settings.poll_interval_seconds,
        help="Polling interval in seconds",
    )
    parser.add_argument("--dry-run", action="store_true", help="Score without POST")
    args = parser.parse_args()

    if args.poll:
        interval = max(5.0, args.interval)
        logger.info(
            "polling_started",
            extra={"event": "polling_started", "interval": interval},
        )
        while True:
            pipeline.run_once(dry_run=args.dry_run)
            time.sleep(interval)
    else:
        pipeline.run_once(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
