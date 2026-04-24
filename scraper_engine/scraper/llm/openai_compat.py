from __future__ import annotations

import asyncio

from openai import AsyncOpenAI

from scraper.llm.config import LLMRuntimeConfig


class OpenAICompatibleClient:
    """OpenAI-compatible chat client (OpenAI cloud, Ollama, or other compatible APIs)."""

    def __init__(self, config: LLMRuntimeConfig) -> None:
        self._config = config
        self._client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout_s,
        )

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._config.model,
            temperature=self._config.temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        if not response.choices:
            raise ValueError("Model response did not include any choices")

        content = response.choices[0].message.content
        if not content:
            raise ValueError("Model response content was empty")

        return content.strip()

    async def get_status(self) -> dict[str, object]:
        """Probe provider reachability and whether target model is listed."""
        probe_timeout_s = min(10.0, self._config.timeout_s)
        try:
            models_page = await asyncio.wait_for(
                self._client.models.list(),
                timeout=probe_timeout_s,
            )
        except TimeoutError as exc:
            raise TimeoutError(
                f"LLM status probe timed out after {probe_timeout_s:.1f}s"
            ) from exc

        model_ids: list[str] = []
        data = getattr(models_page, "data", None)
        if isinstance(data, list):
            for model in data:
                model_id = getattr(model, "id", None)
                if isinstance(model_id, str) and model_id:
                    model_ids.append(model_id)

        return {
            "provider": self._config.provider,
            "base_url": self._config.base_url,
            "target_model": self._config.model,
            "reachable": True,
            "model_available": self._config.model in set(model_ids),
            "listed_model_count": len(model_ids),
            "listed_model_sample": model_ids[:5],
        }
