from __future__ import annotations

from typing import Any
import json
import logging
import requests


class ApiClient:
    """HTTP client for the ASP.NET API."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        api_key_header: str,
        timeout_seconds: float,
        verify_ssl: bool,
        logger: logging.Logger,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._api_key_header = api_key_header
        self._timeout = timeout_seconds
        self._verify_ssl = verify_ssl
        self._logger = logger
        self._session = requests.Session()

    def _build_url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return f"{self._base_url}{path}"

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._api_key:
            headers[self._api_key_header] = self._api_key
        return headers

    def _payload_preview(self, payload: Any, limit: int = 4000) -> str:
        try:
            encoded = json.dumps(payload, ensure_ascii=True)
        except TypeError:
            encoded = str(payload)
        if len(encoded) > limit:
            return f"{encoded[:limit]}..."
        return encoded

    def get_json(self, path: str) -> Any:
        url = self._build_url(path)
        self._logger.info(
            "api_request",
            extra={"event": "api_request", "method": "GET", "url": url},
        )
        try:
            response = self._session.get(
                url,
                headers=self._headers(),
                timeout=self._timeout,
                verify=self._verify_ssl,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            self._logger.error(
                "api_request_failed",
                extra={
                    "event": "api_request_failed",
                    "method": "GET",
                    "url": url,
                    "error": str(exc),
                },
            )
            raise RuntimeError(f"GET {url} failed") from exc

    def post_json(self, path: str, payload: Any) -> Any:
        url = self._build_url(path)
        self._logger.info(
            "api_request",
            extra={
                "event": "api_request",
                "method": "POST",
                "url": url,
                "payload": self._payload_preview(payload),
            },
        )
        try:
            response = self._session.post(
                url,
                headers=self._headers(),
                json=payload,
                timeout=self._timeout,
                verify=self._verify_ssl,
            )
            response.raise_for_status()
            if response.content:
                return response.json()
            return None
        except requests.RequestException as exc:
            self._logger.error(
                "api_request_failed",
                extra={
                    "event": "api_request_failed",
                    "method": "POST",
                    "url": url,
                    "payload": self._payload_preview(payload),
                    "error": str(exc),
                },
            )
            raise RuntimeError(f"POST {url} failed") from exc
