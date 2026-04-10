# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import logging
from collections.abc import Callable
from typing import Optional

from ..models import SummaryResponse
from .base import LLMProvider, LLMProviderError, PartialCallback, ProgressCallback
from ..gemini import GeminiClient, GeminiClientError
from ..gemini.types import Part

logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        api_token: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._model = model
        self._client = GeminiClient(
            api_key=api_key,
            api_token=api_token,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )

    def provider_name(self) -> str:
        return "gemini"

    def supports_streaming(self) -> bool:
        return True

    def supports_image_description(self) -> bool:
        return True

    def _resolve_model(self) -> str:
        if self._model and self._model.strip():
            return self._model.strip()
        return self._model or ""

    def summarize(self, prompt: str, on_partial: PartialCallback | None = None) -> SummaryResponse:
        model = self._resolve_model()
        if not model:
            raise LLMProviderError("Gemini model name is required.")

        try:
            if on_partial:
                accumulated = ""
            for chunk in self._client.stream_content(model=model, contents=prompt):
                accumulated = f"{accumulated}{chunk}"
                on_partial(accumulated, len(accumulated))
            return SummaryResponse(text=accumulated, model=model, provider=self.provider_name())
            response = self._client.generate_content(model=model, contents=prompt)
        except GeminiClientError as error:
            raise LLMProviderError(str(error)) from error
        return SummaryResponse(text=response.text, model=model, provider=self.provider_name())

    def describe_image(
        self,
        image_base64: str,
        prompt: str,
        on_partial: PartialCallback | None = None,
    ) -> SummaryResponse:
        model = self._resolve_model()
        if not model:
            raise LLMProviderError("Gemini model name is required.")
        try:
            image_bytes = base64.b64decode(image_base64)
        except Exception as error:
            raise LLMProviderError(f"Invalid base64 image data: {error}") from error

        try:
            if on_partial:
                accumulated = ""
                image_part = Part.from_bytes(image_bytes=image_bytes, mime_type="image/png")
                for chunk in self._client.stream_content(model=model, contents=[image_part, prompt]):
                    accumulated = f"{accumulated}{chunk}"
                    on_partial(accumulated, len(accumulated))
                return SummaryResponse(text=accumulated, model=model, provider=self.provider_name())
            response = self._client.describe_image(model=model, image_bytes=image_bytes, prompt=prompt)
        except GeminiClientError as error:
            raise LLMProviderError(str(error)) from error
        return SummaryResponse(text=response.text, model=model, provider=self.provider_name())

    def ensure_model_available(self, on_progress: ProgressCallback | None = None) -> str | None:
        model = self._resolve_model()
        if not model:
            raise LLMProviderError("Gemini model name is required.")
        if on_progress:
            on_progress(f"Using Gemini model {model}")
        return model
