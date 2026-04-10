# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from ..models import SummaryResponse
from ..ollama_client import OllamaClient, OllamaClientError
from .base import LLMProvider, LLMProviderError, ProgressCallback, PartialCallback

logger = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    def __init__(
        self,
        model: str | None = None,
        server_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._client = OllamaClient(baseURL=server_url, model=model, timeoutSeconds=timeout_seconds)

    def provider_name(self) -> str:
        return "ollama"

    def supports_streaming(self) -> bool:
        return True

    def supports_image_description(self) -> bool:
        return True

    def _wrap_exception(self, error: Exception) -> LLMProviderError:
        if isinstance(error, LLMProviderError):
            return error
        return LLMProviderError(str(error))

    def summarize(self, prompt: str, on_partial: PartialCallback | None = None) -> SummaryResponse:
        try:
            response = self._client.summarize(prompt, onPartial=on_partial)
        except OllamaClientError as error:
            raise self._wrap_exception(error) from error
        return SummaryResponse(text=response.text, model=response.model, provider=self.provider_name())

    def describe_image(
        self,
        image_base64: str,
        prompt: str,
        on_partial: PartialCallback | None = None,
    ) -> SummaryResponse:
        try:
            response = self._client.describeImage(image_base64, prompt=prompt, onPartial=on_partial)
        except OllamaClientError as error:
            raise self._wrap_exception(error) from error
        return SummaryResponse(text=response.text, model=response.model, provider=self.provider_name())

    def ensure_model_available(self, on_progress: ProgressCallback | None = None) -> str | None:
        def progress_adapter(event: dict[str, Any]) -> None:
            if on_progress is None:
                return
            status = event.get("status") or event.get("message") or event.get("error")
            on_progress(str(status or event))

        try:
            return self._client.ensureModelInstalled(onProgress=progress_adapter if on_progress else None)
        except OllamaClientError as error:
            raise self._wrap_exception(error) from error
