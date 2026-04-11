# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
from logHandler import log
from collections.abc import Callable
from typing import Any, Optional

from ..models import LLMResponse, SummaryResponse, ToolCall
from .base import LLMProvider, LLMProviderError, PartialCallback, ProgressCallback
from .config import GeminiConfig
from ..gemini import GeminiClient, GeminiClientError
from ..gemini.types import Content, GenerateContentConfig, Part
from ..core.canonical import Message, Tool


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

    def _convert_message_to_content(self, message: Message) -> Content | dict[str, Any]:
        has_function_parts = False
        part_items: list[Any] = []

        for part in message.parts:
            if part.type == "text":
                part_items.append(Part(text=part.text or "", role=message.role))
            elif part.type == "image":
                if part.image is not None:
                    part_items.append(Part.from_bytes(part.image, mime_type="image/png", role=message.role))
            elif part.type == "tool_call":
                has_function_parts = True
                part_items.append(
                    {
                        "functionCall": {
                            "name": part.tool_name or "",
                            "arguments": part.tool_args or {},
                        }
                    }
                )
            elif part.type == "tool_result":
                has_function_parts = True
                part_items.append(
                    {
                        "functionResponse": {
                            "name": part.tool_name or "",
                            "response": self._normalize_function_response(part.tool_result, part.text),
                        }
                    }
                )

        if has_function_parts:
            payload_parts: list[dict[str, Any]] = []
            for item in part_items:
                if isinstance(item, Part):
                    payload_parts.append(item.to_dict())
                else:
                    payload_parts.append(item)
            return {"role": message.role, "parts": payload_parts}

        return Content(parts=[item for item in part_items if isinstance(item, Part)], role=message.role)

    def _normalize_function_response(self, tool_result: dict[str, Any] | None, fallback_text: str | None) -> dict[str, Any]:
        if isinstance(tool_result, dict):
            return tool_result

        if fallback_text is None or fallback_text == "":
            return {}

        return {"text": fallback_text}

    def _convert_tool(self, tool: Tool) -> dict[str, Any]:
        return {
            "functionDeclarations": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                }
            ]
        }

    def _handle_chat(self, messages: list[Message], tools: list[Tool] | None, stream_handler: PartialCallback | None) -> LLMResponse:
        log.debug(
            "GeminiProvider._handle_chat: canonical_messages=%s tools=%s stream=%s",
            [(msg.role, [part.type for part in msg.parts]) for msg in messages],
            [tool.name for tool in tools] if tools else None,
            stream_handler is not None,
        )
        if not messages:
            return LLMResponse(text="No input provided", model="gemini", raw=None, metrics=None)

        contents: list[Any] = [self._convert_message_to_content(msg) for msg in messages]
        gemini_tools = [self._convert_tool(tool) for tool in tools] if tools else None

        log.debug(
            "GeminiProvider._handle_chat: provider_payload=%s tools=%s",
            contents,
            gemini_tools,
        )

        if self._supports_multimodal():
            return self._handle_multimodal_chat(messages, tools, stream_handler)

        return self._handle_chat_fallback(messages)

    def _extract_tool_calls(self, raw_response: Any) -> list[ToolCall] | None:
        log.debug("GeminiProvider._extract_tool_calls: raw_response=%s", raw_response)
        if not isinstance(raw_response, dict):
            log.debug("GeminiProvider._extract_tool_calls: raw response is not a dict")
            return None

        tool_calls = raw_response.get("tool_calls") or raw_response.get("toolCalls")
        if isinstance(tool_calls, list):
            normalized = self._normalize_tool_calls(tool_calls)
            log.debug("GeminiProvider._extract_tool_calls: extracted top-level tool_calls=%s", [tc.name for tc in normalized] if normalized else None)
            return normalized

        # Official Gemini streaming/function-call responses may embed function call objects in candidates.
        candidates = raw_response.get("candidates")
        if isinstance(candidates, list):
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                content = candidate.get("content")
                if isinstance(content, dict):
                    if content.get("type") == "function_call":
                        normalized = self._normalize_tool_calls([content])
                        log.debug("GeminiProvider._extract_tool_calls: extracted function_call candidate=%s", [tc.name for tc in normalized] if normalized else None)
                        return normalized
                    if content.get("type") == "tool_call":
                        normalized = self._normalize_tool_calls([content])
                        log.debug("GeminiProvider._extract_tool_calls: extracted tool_call candidate=%s", [tc.name for tc in normalized] if normalized else None)
                        return normalized
                    # nested message-style function call block
                    function_call = content.get("function_call") or content.get("tool_call")
                    if isinstance(function_call, dict):
                        normalized = self._normalize_tool_calls([function_call])
                        log.debug("GeminiProvider._extract_tool_calls: extracted nested function_call/tool_call=%s", [tc.name for tc in normalized] if normalized else None)
                        return normalized
                    # Gemini may embed function call payloads inside content.parts as functionCall/args
                    parts = content.get("parts")
                    if isinstance(parts, list):
                        for part in parts:
                            if not isinstance(part, dict):
                                continue
                            function_call = part.get("function_call") or part.get("tool_call") or part.get("functionCall")
                            if isinstance(function_call, dict):
                                normalized = self._normalize_tool_calls([function_call])
                                log.debug("GeminiProvider._extract_tool_calls: extracted part-level functionCall=%s", [tc.name for tc in normalized] if normalized else None)
                                return normalized

        log.debug("GeminiProvider._extract_tool_calls: no tool calls found")
        return None

    def _normalize_tool_calls(self, tool_calls: list[Any]) -> list[ToolCall] | None:
        calls: list[ToolCall] = []
        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            if "function" in tc and isinstance(tc.get("function"), dict):
                function_payload = tc["function"]
                name = str(function_payload.get("name", "")).strip()
                arguments = function_payload.get("arguments") if isinstance(function_payload.get("arguments"), dict) else {}
            elif "functionCall" in tc and isinstance(tc.get("functionCall"), dict):
                function_payload = tc["functionCall"]
                name = str(function_payload.get("name", "")).strip()
                arguments = function_payload.get("args") if isinstance(function_payload.get("args"), dict) else {}
            else:
                name = str(tc.get("name", "")).strip()
                arguments = tc.get("arguments") if isinstance(tc.get("arguments"), dict) else {}
            if not name:
                continue
            calls.append(ToolCall(name=name, arguments=arguments, id=tc.get("id")))
        return calls or None

    def _handle_multimodal_chat(
        self,
        messages: list[Message],
        tools: list[Tool] | None,
        stream_handler: PartialCallback | None,
    ) -> LLMResponse:
        contents: list[Any] = []
        system_instruction: Content | None = None
        for msg in messages:
            if msg.role == "system":
                text = "".join(part.text or "" for part in msg.parts if part.type == "text")
                if text:
                    if system_instruction is None:
                        system_instruction = Content(parts=[Part(text=text, role="system")], role="system")
                    else:
                        system_instruction.parts.append(Part(text=text, role="system"))
                continue

            content_item = self._convert_message_to_content(msg)
            if content_item:
                contents.append(content_item)

        gemini_tools = [self._convert_tool(tool) for tool in tools] if tools else None
        log.debug(
            "GeminiProvider._handle_multimodal_chat: model=%s contents=%s systemInstruction=%s tools=%s stream=%s",
            self._resolve_model(),
            [item.to_dict() if isinstance(item, Content) else item for item in contents],
            system_instruction.to_dict() if system_instruction is not None else None,
            [tool.name for tool in tools] if tools else None,
            stream_handler is not None,
        )
        if stream_handler is not None and gemini_tools is None:
            log.debug(
                "GeminiProvider._handle_multimodal_chat: streaming without tools, contents=%s systemInstruction=%s",
                [item.to_dict() if isinstance(item, Content) else item for item in contents],
                system_instruction.to_dict() if system_instruction is not None else None,
            )
            text_output = ""
            for chunk in self._client.stream_content(
                model=self._resolve_model(),
                contents=contents,
                config=self._build_generation_config(),
                tools=gemini_tools,
                system_instruction=system_instruction,
            ):
                text_output += chunk
                stream_handler(text_output, len(text_output))
            return LLMResponse(text=text_output, model="gemini", raw=None, metrics=None)

        response = self._client.generate_content(
            model=self._resolve_model(),
            contents=contents,
            config=self._build_generation_config(),
            tools=gemini_tools,
            system_instruction=system_instruction,
        )
        if stream_handler is not None and response.text:
            stream_handler(response.text, len(response.text))
        tool_calls = self._extract_tool_calls(response.raw)
        log.debug(
            "GeminiProvider._handle_multimodal_chat response: text_len=%d candidates=%s raw_keys=%s tool_calls=%s",
            len(response.text or ""),
            len(response.candidates) if response.candidates is not None else None,
            list(response.raw.keys()) if isinstance(response.raw, dict) else None,
            [tc.name for tc in tool_calls] if tool_calls else None,
        )
        return LLMResponse(
            text=response.text,
            model="gemini",
            raw=response,
            metrics=None,
            tool_calls=tool_calls,
        )

    def _handle_chat_fallback(self, messages: list[Message]) -> LLMResponse:
        prompt = "\n".join(
            "".join(part.text or "" for part in message.parts if part.type == "text")
            for message in messages
        )
        result = self.summarize(prompt)
        return LLMResponse(text=result.text, model=result.model, raw=result, metrics=None)

    def generate(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        stream_handler: PartialCallback | None = None,
    ) -> LLMResponse:
        if not messages:
            return LLMResponse(text="No input provided", model="gemini", raw=None, metrics=None)
        return self._handle_chat(messages=messages, tools=tools, stream_handler=stream_handler)

    def ensure_model_available(self, on_progress: ProgressCallback | None = None) -> str | None:
        model = self._resolve_model()
        if not model:
            raise LLMProviderError("Gemini model name is required.")
        if on_progress:
            on_progress(f"Using Gemini model {model}")
        return model
