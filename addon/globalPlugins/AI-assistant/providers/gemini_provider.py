# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import logging
from collections.abc import Callable
from typing import Optional

from ..models import LLMRequest, LLMResponse, SummaryResponse, TaskType
from .base import LLMProvider, LLMProviderError, PartialCallback, ProgressCallback, format_chat_messages
from .config import GeminiConfig
from ..gemini import GeminiClient, GeminiClientError
from ..gemini.types import Content, GenerateContentConfig, Part

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

    def summarize(self, prompt: str, stream_handler: PartialCallback | None = None) -> SummaryResponse:
        model = self._resolve_model()
        if not model:
            raise LLMProviderError("Gemini model name is required.")

        try:
            config = self._build_generation_config()
            if stream_handler is not None:
                accumulated = ""
                for chunk in self._client.stream_content(model=model, contents=prompt, config=config):
                    accumulated = f"{accumulated}{chunk}"
                    stream_handler(accumulated, len(accumulated))
                return SummaryResponse(text=accumulated, model=model, provider=self.provider_name())

            response = self._client.generate_content(model=model, contents=prompt, config=config)
        except GeminiClientError as error:
            raise LLMProviderError(str(error)) from error
        return SummaryResponse(text=response.text, model=model, provider=self.provider_name())

    def describe_image(
        self,
        image_base64: str,
        prompt: str,
        stream_handler: PartialCallback | None = None,
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
            if stream_handler is not None:
                accumulated = ""
                image_part = Part.from_bytes(image_bytes, mime_type="image/png")
                for chunk in self._client.stream_content(model=model, contents=[image_part, prompt], config=config):
                    accumulated = f"{accumulated}{chunk}"
                    stream_handler(accumulated, len(accumulated))
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

    def _supports_multimodal(self) -> bool:
        return True

    def _handle_chat(self, request: LLMRequest) -> LLMResponse:
        if not request.messages:
            return LLMResponse(text="No input provided", model="gemini", raw=None, metrics=None)

        if self._supports_multimodal():
            return self._handle_multimodal_chat(request)

        return self._handle_chat_fallback(request)

    def _handle_multimodal_chat(self, request: LLMRequest) -> LLMResponse:
        parts: list[Part] = []
        for msg in request.messages or []:
            role_prefix = f"{msg.role.upper()}: "
            if msg.content:
                parts.append(Part(text=role_prefix + msg.content, role=msg.role))
            if msg.image_base64:
                parts.append(Part.from_base64(msg.image_base64, mime_type="image/png", role=msg.role))

        contents = [Content(parts=parts)]

        if request.stream_handler is not None:
            text_output = ""
            for chunk in self._client.stream_content(model=self._resolve_model(), contents=contents, config=self._build_generation_config()):
                text_output += chunk
                request.stream_handler(chunk)
            return LLMResponse(text=text_output, model="gemini", raw=None, metrics=None)

        response = self._client.generate_content(model=self._resolve_model(), contents=contents, config=self._build_generation_config())
        return LLMResponse(text=response.text, model="gemini", raw=response, metrics=None)

    def _handle_chat_fallback(self, request: LLMRequest) -> LLMResponse:
        prompt = format_chat_messages(request.messages)
        result = self.summarize(prompt, stream_handler=request.stream_handler)
        return LLMResponse(text=result.text, model=result.model, raw=result, metrics=None)

    def generate(self, request: LLMRequest) -> LLMResponse:
        if request.task_type == TaskType.SUMMARY:
            response = self.summarize(request.input_text or "", stream_handler=request.stream_handler)
            return LLMResponse(text=response.text, model=response.model, raw=None, metrics=None)

        if request.task_type == TaskType.IMAGE_DESCRIPTION:
            if request.image_base64 is None:
                raise LLMProviderError("Image base64 data is required for image_description.")
            response = self.describe_image(
                request.image_base64,
                request.input_text or "",
                stream_handler=request.stream_handler,
            )
            return LLMResponse(text=response.text, model=response.model, raw=None, metrics=None)

        if request.task_type == TaskType.CHAT:
            return self._handle_chat(request)

        raise LLMProviderError(f"Unsupported task type: {request.task_type}")

    def ensure_model_available(self, on_progress: ProgressCallback | None = None) -> str | None:
        model = self._resolve_model()
        if not model:
            raise LLMProviderError("Gemini model name is required.")
        if on_progress:
            on_progress(f"Using Gemini model {model}")
        return model
