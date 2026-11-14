"""Client for the MLflow model server. The backend only calls it over REST,
so the model can be changed or rolled back without touching the API."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from app.metrics import MODEL_ERRORS, MODEL_LATENCY, MODEL_SERVER_UP


class ModelUnavailableError(Exception):
    """The model server cannot be reached or has no model loaded."""


class ModelResponseError(Exception):
    """The model server answered with an error or an unexpected payload."""


class ModelServerClient:
    """Async client: ``POST {base_url}/invocations`` with dataframe_records."""

    def __init__(self, base_url: str, timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def ping(self) -> bool:
        """True if the model server reports healthy."""
        try:
            resp = await self._client.get(f"{self.base_url}/ping", timeout=3.0)
            up = resp.status_code == 200
        except httpx.HTTPError:
            up = False
        MODEL_SERVER_UP.set(1 if up else 0)
        return up

    async def predict(self, texts: list[str], top_k_similar: int = 3) -> list[dict[str, Any]]:
        """Return one prediction dict per text."""
        payload = {"dataframe_records": [{"text": t, "top_k_similar": top_k_similar} for t in texts]}
        start = time.perf_counter()
        try:
            resp = await self._client.post(f"{self.base_url}/invocations", json=payload)
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            MODEL_ERRORS.labels(type="unavailable").inc()
            MODEL_SERVER_UP.set(0)
            raise ModelUnavailableError(f"Model server unreachable: {type(exc).__name__}") from exc
        finally:
            MODEL_LATENCY.observe(time.perf_counter() - start)

        if resp.status_code == 503:
            MODEL_ERRORS.labels(type="unavailable").inc()
            raise ModelUnavailableError("Model server is starting or has no model loaded")
        if resp.status_code != 200:
            MODEL_ERRORS.labels(type="http_error").inc()
            raise ModelResponseError(f"Model server returned HTTP {resp.status_code}: {resp.text[:200]}")
        MODEL_SERVER_UP.set(1)
        try:
            predictions = resp.json()["predictions"]
            return [json.loads(p["result"]) for p in predictions]
        except (KeyError, TypeError, ValueError) as exc:
            MODEL_ERRORS.labels(type="bad_payload").inc()
            raise ModelResponseError(f"Unexpected model server payload: {exc}") from exc
