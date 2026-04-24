from __future__ import annotations

from typing import Any
from typing import Protocol


class LLMClientPort(Protocol):
    """Application-facing contract for any LLM completion client."""

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> str:
        """Return raw model text containing a JSON object."""

    async def get_status(self) -> dict[str, Any]:
        """Return provider/model availability diagnostics."""
