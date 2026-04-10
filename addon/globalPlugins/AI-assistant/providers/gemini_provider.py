# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import logging
from collections.abc import Callable
from typing import Optional

from ..models import SummaryResponse
from .base import LLMProvider, LLMProviderError, PartialCallback, ProgressCallback
from .config import GeminiConfig
from ..gemini import GeminiClient, GeminiClientError
from ..gemini.types import GenerateContentConfig, Part

logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    def __init__(self, config: GeminiConfig) -> None:
        self._config = config
        self._client = GeminiClient(
            api_key=config.api_key,
            api_token=config.api_token,
            base_url=config.base_url,
            timeout_seconds=config.timeout_seconds,
        )

    def provider_name(self) -> str:
        return "gemini"

    def supports_streaming(self) -> bool:
        return True

    def supports_image_description(self) -> bool:
        return True

    def _resolve_model(self) -> str:
        model = self._config.model_name
        return model.strip() if model else ""

    def summarize(self, prompt: str, on_partial: PartialCallback | None = None) -> SummaryResponse:
        model = self._resolve_model()
        if not model:
            raise LLMProviderError("Gemini model name is required.")

        try:
            config = self._build_generation_config()
            if on_partial:
                accumulated = ""
                for chunk in self._client.stream_content(model=model, contents=prompt, config=config):
                    accumulated = f"{accumulated}{chunk}"
                    on_partial(accumulated, len(accumulated))
                return SummaryResponse(text=accumulated, model=model, provider=self.provider_name())

            response = self._client.generate_content(model=model, contents=prompt, config=config)
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
            config = self._build_generation_config()
            if on_partial:
                accumulated = ""
                image_part = Part.from_bytes(image_bytes, mime_type="image/png")
                for chunk in self._client.stream_content(model=model, contents=[image_part, prompt], config=config):
                    accumulated = f"{accumulated}{chunk}"
                    on_partial(accumulated, len(accumulated))
                return SummaryResponse(text=accumulated, model=model, provider=self.provider_name())
            response = self._client.describe_image(model=model, image_bytes=image_bytes, prompt=prompt, config=config)
        except GeminiClientError as error:
            raise LLMProviderError(str(error)) from error
        return SummaryResponse(text=response.text, model=model, provider=self.provider_name())

    def _build_generation_config(self) -> GenerateContentConfig:
        return GenerateContentConfig(
            temperature=self._config.generate_temperature,
            top_p=self._config.generate_top_p,
            top_k=self._config.generate_top_k,
        )

    def list_models(self, page_size: int = 50, page_token: Optional[str] = None):
        return self._client.list_models(page_size=page_size, page_token=page_token)

    def get_model_info(self, model_name: str):
        return self._client.get_model(model_name)

    def ensure_model_available(self, on_progress: ProgressCallback | None = None) -> str | None:
        model = self._resolve_model()
        if not model:
            raise LLMProviderError("Gemini model name is required.")
        if on_progress:
            on_progress(f"Using Gemini model {model}")
        return model
