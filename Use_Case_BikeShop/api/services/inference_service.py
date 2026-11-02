"""
Connection to BFH inference (MLMP), SPEC §8.1.

We only build the connection: a configured client for the colleague's LLM
tools, and a check that the endpoint is reachable. Nothing in the shop calls
the model yet. The key is never logged or returned.
"""
import time

import httpx
from openai import OpenAI

from ..config import (
    MLMP_BASE_URL, MLMP_API_KEY, MLMP_MODEL,
    INFERENCE_CHECK_TTL_SECONDS, INFERENCE_CHECK_TIMEOUT_SECONDS,
)

OK = "ok"
UNREACHABLE = "unreachable"
UNAUTHORIZED = "unauthorized"
MODEL_MISSING = "model_missing"
NOT_CONFIGURED = "not_configured"


class InferenceService:
    """
    Service class for the BFH inference endpoint.
    """
    # Shared by all instances in this process: one cached result per worker.
    _cached_status: str | None = None
    _cached_at: float = 0.0

    def __init__(self, base_url: str = MLMP_BASE_URL, api_key: str = MLMP_API_KEY, model: str = MLMP_MODEL):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    def get_client(self) -> OpenAI:
        """An OpenAI-compatible client pointed at BFH inference, for the LLM tools."""
        if not self.is_configured():
            raise RuntimeError("BFH inference is not configured: set MLMP_API_KEY (and optionally "
                               "MLMP_BASE_URL, MLMP_MODEL) in .env.")
        return OpenAI(base_url=self.base_url, api_key=self.api_key)

    def _probe(self) -> str:
        """List the models (spends no tokens) and classify the answer."""
        if not self.is_configured():
            return NOT_CONFIGURED
        try:
            response = httpx.get(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=INFERENCE_CHECK_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError:
            return UNREACHABLE
        if response.status_code in (401, 403):
            return UNAUTHORIZED
        if response.status_code != 200:
            return UNREACHABLE
        try:
            model_ids = {m.get("id") for m in response.json().get("data", [])}
        except ValueError:
            return UNREACHABLE
        return OK if self.model in model_ids else MODEL_MISSING

    def check(self) -> str:
        """ok | unreachable | unauthorized | model_missing | not_configured, cached for 60 s."""
        cls = type(self)
        now = time.monotonic()
        if cls._cached_status is None or now - cls._cached_at >= INFERENCE_CHECK_TTL_SECONDS:
            cls._cached_status = self._probe()
            cls._cached_at = now
        return cls._cached_status

    @classmethod
    def clear_cache(cls) -> None:
        cls._cached_status = None
        cls._cached_at = 0.0
