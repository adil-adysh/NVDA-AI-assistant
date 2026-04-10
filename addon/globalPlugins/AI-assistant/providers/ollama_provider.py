# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from ..models import LLMRequest, LLMResponse, SummaryResponse, TaskType
from ..ollama_client import OllamaClient, OllamaClientError
from .base import LLMProvider, LLMProviderError, ProgressCallback, PartialCallback, format_chat_messages
from .config import OllamaConfig

logger = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    def __init__(self, config: OllamaConfig) -> None:
        self._config = config
        self._client = OllamaClient(
            baseURL=config.server_url,
            model=config.model_name,
            timeoutSeconds=config.timeout_seconds,
        )

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

    def summarize(self, prompt: str, stream_handler: PartialCallback | None = None) -> SummaryResponse:
        try:
            response = self._client.summarize(prompt, onPartial=stream_handler)
        except OllamaClientError as error:
            raise self._wrap_exception(error) from error
        return SummaryResponse(text=response.text, model=response.model, provider=self.provider_name())

    def describe_image(
        self,
        image_base64: str,
        prompt: str,
        stream_handler: PartialCallback | None = None,
    ) -> SummaryResponse:
        try:
            response = self._client.describeImage(image_base64, prompt=prompt, onPartial=stream_handler)
        except OllamaClientError as error:
            raise self._wrap_exception(error) from error
        return SummaryResponse(text=response.text, model=response.model, provider=self.provider_name())

    def _handle_chat(self, request: LLMRequest) -> LLMResponse:
        if not request.messages:
            return LLMResponse(text="No input provided", model=self.provider_name(), raw=None, metrics=None)

        messages = []
        for msg in request.messages:
            if msg is None:
                continue
            chat_message: dict[str, Any] = {
                "role": msg.role,
                "content": msg.content or "",
            }
            if msg.image_base64:
                chat_message["images"] = [msg.image_base64]
            if msg.tool_name:
                chat_message["tool_name"] = msg.tool_name
            if msg.tool_calls:
                chat_message["tool_calls"] = msg.tool_calls
            messages.append(chat_message)

        if not messages:
            return self._handle_chat_fallback(request)

        try:
            response = self._client.chat(messages, tools=request.tools, onPartial=request.stream_handler)
        except OllamaClientError as error:
            raise self._wrap_exception(error) from error

        return LLMResponse(text=response.text, model=response.model, raw=response, metrics=None)

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
        def progress_adapter(event: dict[str, Any]) -> None:
            if on_progress is None:
                return
            status = event.get("status") or event.get("message") or event.get("error")
            on_progress(str(status or event))

        try:
            return self._client.ensureModelInstalled(onProgress=progress_adapter if on_progress else None)
        except OllamaClientError as error:
            raise self._wrap_exception(error) from error
