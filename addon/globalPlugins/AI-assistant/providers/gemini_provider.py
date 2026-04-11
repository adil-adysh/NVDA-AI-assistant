# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
from logHandler import log
from collections.abc import Callable
from typing import Optional

from ..models import LLMRequest, LLMResponse, SummaryResponse, TaskType, ToolCall
from .base import LLMProvider, LLMProviderError, PartialCallback, ProgressCallback, format_chat_messages
from .config import GeminiConfig
from ..gemini import GeminiClient, GeminiClientError
from ..gemini.types import Content, GenerateContentConfig, Part


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
        log.debug(
            "GeminiProvider._handle_chat: task_type=%s messages=%s tools=%s stream=%s",
            request.task_type,
            [(msg.role, msg.content) for msg in request.messages] if request.messages else None,
            request.tools,
            request.stream,
        )
        if not request.messages:
            return LLMResponse(text="No input provided", model="gemini", raw=None, metrics=None)

        if self._supports_multimodal():
            return self._handle_multimodal_chat(request)

        return self._handle_chat_fallback(request)

    def _extract_tool_calls(self, raw_response: Any) -> list[ToolCall] | None:
        if not isinstance(raw_response, dict):
            return None

        tool_calls = raw_response.get("tool_calls") or raw_response.get("toolCalls")
        if isinstance(tool_calls, list):
            return self._normalize_tool_calls(tool_calls)

        # Official Gemini streaming/function-call responses may embed function call objects in candidates.
        candidates = raw_response.get("candidates")
        if isinstance(candidates, list):
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                content = candidate.get("content")
                if isinstance(content, dict):
                    if content.get("type") == "function_call":
                        return self._normalize_tool_calls([content])
                    if content.get("type") == "tool_call":
                        return self._normalize_tool_calls([content])
                    # nested message-style function call block
                    function_call = content.get("function_call") or content.get("tool_call")
                    if isinstance(function_call, dict):
                        return self._normalize_tool_calls([function_call])

        return None

    def _normalize_tool_calls(self, tool_calls: list[Any]) -> list[ToolCall] | None:
        calls: list[ToolCall] = []
        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            name = str(tc.get("name", "")).strip()
            if not name:
                continue
            arguments = tc.get("arguments") if isinstance(tc.get("arguments"), dict) else {}
            calls.append(ToolCall(name=name, arguments=arguments, id=tc.get("id")))
        return calls or None

    def _handle_multimodal_chat(self, request: LLMRequest) -> LLMResponse:
        contents: list[Content] = []
        system_instruction: Content | None = None
        for msg in request.messages or []:
            if msg.role == "system":
                if msg.content:
                    if system_instruction is None:
                        system_instruction = Content(parts=[Part(text=msg.content, role="system")], role="system")
                    else:
                        system_instruction.parts.append(Part(text=msg.content, role="system"))
                continue

            if msg.content:
                contents.append(
                    Content(
                        parts=[Part(text=msg.content, role=msg.role)],
                        role=msg.role,
                    )
                )
            if msg.image_base64:
                contents.append(
                    Content(
                        parts=[Part.from_base64(msg.image_base64, mime_type="image/png", role=msg.role)],
                        role=msg.role,
                    )
                )

        log.debug(
            "GeminiProvider._handle_multimodal_chat: model=%s contents=%s systemInstruction=%s tools=%s stream=%s",
            self._resolve_model(),
            [content.to_dict() for content in contents],
            system_instruction.to_dict() if system_instruction is not None else None,
            request.tools,
            request.stream_handler is not None,
        )
        if request.stream_handler is not None:
            text_output = ""
            for chunk in self._client.stream_content(
                model=self._resolve_model(),
                contents=contents,
                config=self._build_generation_config(),
                tools=request.tools,
                system_instruction=system_instruction,
            ):
                text_output += chunk
                request.stream_handler(text_output, len(text_output))
            return LLMResponse(text=text_output, model="gemini", raw=None, metrics=None)

        response = self._client.generate_content(
            model=self._resolve_model(),
            contents=contents,
            config=self._build_generation_config(),
            tools=request.tools,
            system_instruction=system_instruction,
        )
        log.debug(
            "GeminiProvider._handle_multimodal_chat response: text_len=%d candidates=%s raw_keys=%s",
            len(response.text or ""),
            len(response.candidates) if response.candidates is not None else None,
            list(response.raw.keys()) if isinstance(response.raw, dict) else None,
        )
        return LLMResponse(
            text=response.text,
            model="gemini",
            raw=response,
            metrics=None,
            tool_calls=self._extract_tool_calls(response.raw),
        )

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
