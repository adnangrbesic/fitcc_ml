from __future__ import annotations

import logging
from time import perf_counter

from scraper.llm.config import LLMRuntimeConfig, build_config
from scraper.llm.json_utils import parse_json_object
from scraper.llm.openai_compat import OpenAICompatibleClient
from scraper.llm.ports import LLMClientPort
from scraper.llm.template_loader import (
    load_json_document,
    load_prompt_template,
    render_user_prompt,
)
from scraper.llm.validator import StrictSchemaValidator
from scraper.models import ListingData

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = (
    "You are a strict JSON data extraction engine. "
    "Follow the user instructions exactly and return only valid JSON."
)


class ListingEnricher:
    """Enriches listings with LLM output and strict schema validation."""

    def __init__(
        self,
        *,
        config: LLMRuntimeConfig,
        llm_client: LLMClientPort,
        prompt_template: str,
        output_template: dict,
        schema_validator: StrictSchemaValidator | None,
    ) -> None:
        self._config = config
        self._llm_client = llm_client
        self._prompt_template = prompt_template
        self._output_template = output_template
        self._schema_validator = schema_validator

    async def enrich(self, listings: list[ListingData]) -> list[ListingData]:
        enriched: list[ListingData] = []
        for listing in listings:
            enriched.append(await self.enrich_listing(listing))
        return enriched

    async def log_status(self) -> None:
        """Probe LLM provider/model status and emit logs for observability."""
        try:
            status = await self._llm_client.get_status()
            logger.info(
                "LLM status: provider=%s model=%s reachable=%s model_available=%s listed_models=%s",
                status.get("provider"),
                status.get("target_model"),
                status.get("reachable"),
                status.get("model_available"),
                status.get("listed_model_count"),
            )

            sample = status.get("listed_model_sample")
            if isinstance(sample, list) and sample:
                logger.info("LLM listed model sample: %s", ", ".join(sample))
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM status probe failed: %s", exc)

    async def enrich_listing(self, listing: ListingData) -> ListingData:
        listing_payload = listing.model_dump(mode="json")
        max_attempts = self._config.max_retries + 1
        last_error = ""
        last_latency_ms = 0

        for attempt in range(1, max_attempts + 1):
            started = perf_counter()
            try:
                user_prompt = render_user_prompt(
                    prompt_template=self._prompt_template,
                    output_template=self._output_template,
                    listing_payload=listing_payload,
                )
                raw_response = await self._llm_client.complete_json(
                    system_prompt=_DEFAULT_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                )
                enrichment = parse_json_object(raw_response)
                if self._schema_validator is not None:
                    self._schema_validator.validate(enrichment)

                last_latency_ms = int((perf_counter() - started) * 1000)
                listing.llm_enrichment = enrichment
                listing.llm_meta = {
                    "provider": self._config.provider,
                    "model": self._config.model,
                    "category": self._config.category,
                    "status": "ok",
                    "attempts": attempt,
                    "latency_ms": last_latency_ms,
                    "error": None,
                }
                return listing
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                last_latency_ms = int((perf_counter() - started) * 1000)
                logger.warning(
                    "LLM enrichment failed for item %s (attempt %d/%d): %s",
                    listing.item_id,
                    attempt,
                    max_attempts,
                    exc,
                )

        listing.llm_enrichment = None
        listing.llm_meta = {
            "provider": self._config.provider,
            "model": self._config.model,
            "category": self._config.category,
            "status": "failed",
            "attempts": max_attempts,
            "latency_ms": last_latency_ms,
            "error": last_error,
        }
        return listing


def build_enricher(
    *,
    category: str,
    prompt_template_path: str | None = None,
    output_template_path: str | None = None,
    output_schema_path: str | None = None,
    validate_output_schema: bool | None = None,
) -> ListingEnricher:
    config = build_config(
        category=category,
        prompt_template_path=prompt_template_path,
        output_template_path=output_template_path,
        output_schema_path=output_schema_path,
        validate_output_schema=validate_output_schema,
    )

    prompt_template = load_prompt_template(config.prompt_template_path)
    output_template = load_json_document(config.output_template_path)
    schema_validator: StrictSchemaValidator | None = None
    if config.validate_output_schema:
        output_schema = load_json_document(config.output_schema_path)
        schema_validator = StrictSchemaValidator(output_schema)

    llm_client = OpenAICompatibleClient(config)

    return ListingEnricher(
        config=config,
        llm_client=llm_client,
        prompt_template=prompt_template,
        output_template=output_template,
        schema_validator=schema_validator,
    )
