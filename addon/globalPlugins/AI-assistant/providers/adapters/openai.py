# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from typing import Any

from ...core.canonical import Message, Tool
from ...core.messages import LLMResponse, SummaryResponse
from ...core.tooling import ToolCall
from ...tools import build_function_tool_definition, normalize_tool_calls
from ...openai import OpenAIClient, OpenAIClientError
from ..config import OpenAIConfig
from ..interfaces import LLMProvider, LLMProviderError, PartialCallback, ProgressCallback


class OpenAIProvider(LLMProvider):
    def __init__(self, config: OpenAIConfig) -> None:
        self._config = config
        try:
            self._client = OpenAIClient(
                api_key=config.api_key,
                base_url=config.base_url,
                chat_path=config.chat_path,
                timeout_seconds=config.timeout_seconds,
            )
        except OpenAIClientError as error:
            raise self._wrap_exception(error) from error

    def provider_name(self) -> str:
        return "openai"

    def supports_streaming(self) -> bool:
        return False

    def supports_image_description(self) -> bool:
        return False

    def _wrap_exception(self, error: Exception) -> LLMProviderError:
        if isinstance(error, LLMProviderError):
            return error
        return LLMProviderError(str(error))

    def _resolve_model(self) -> str:
        model = self._config.model_name
        if not model:
            raise LLMProviderError("OpenAI model name is required.")
        return model.strip()

    def summarize(self, prompt: str, stream_handler: PartialCallback | None = None) -> SummaryResponse:
        model = self._resolve_model()
        try:
            response = self._client.create_chat_completion(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that summarizes text concisely."},
                    {"role": "user", "content": prompt},
                ],
                temperature=self._config.generate_temperature,
                top_p=self._config.generate_top_p,
                top_k=self._config.generate_top_k,
                max_tokens=self._config.generate_max_tokens,
            )
        except OpenAIClientError as error:
            raise self._wrap_exception(error) from error

        choice = self._parse_choice(response)
        return SummaryResponse(text=choice.get("content", ""), model=model, provider=self.provider_name())

    def describe_image(
        self,
        image_base64: str,
        prompt: str,
        stream_handler: PartialCallback | None = None,
    ) -> SummaryResponse:
        raise LLMProviderError("Image description is not supported by the OpenAI provider.")

    def _convert_message(self, message: Message) -> dict[str, Any]:
        content_parts: list[str] = []
        for part in message.parts:
            if part.type == "text" and part.text is not None:
                content_parts.append(part.text)
            elif part.type == "tool_result":
                if part.tool_result is not None:
                    content_parts.append(json.dumps(part.tool_result))
                elif part.text is not None:
                    content_parts.append(part.text)
            elif part.type == "image":
                content_parts.append("[IMAGE ATTACHED]")
            elif part.type == "tool_call":
                content_parts.append(
                    f"[tool call: {part.tool_name or 'unknown'} arguments={json.dumps(part.tool_args or {})}]"
                )

        return {
            "role": message.role,
            "content": "\n".join(content_parts) if content_parts else "",
        }

    def _build_function_definitions(self, tools: list[Tool] | None) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        return [build_function_tool_definition(tool)["function"] for tool in tools]

    def _parse_choice(self, response: dict[str, Any]) -> dict[str, Any]:
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            return {}
        choice = choices[0]
        if not isinstance(choice, dict):
            return {}
        message = choice.get("message")
        if isinstance(message, dict):
            return message
        return {}

    def _extract_tool_calls(self, choice: dict[str, Any]) -> list[ToolCall] | None:
        function_call = choice.get("function_call")
        if isinstance(function_call, dict):
            return normalize_tool_calls(
                [
                    {
                        "functionCall": {
                            "name": function_call.get("name", ""),
                            "args": function_call.get("arguments", {}),
                        }
                    }
                ]
            )
        return None

    def _handle_chat(
        self,
        messages: list[Message],
        tools: list[Tool] | None,
        stream_handler: PartialCallback | None,
    ) -> LLMResponse:
        if not messages:
            return LLMResponse(text="No input provided", model=self.provider_name(), raw=None, metrics=None)

        payload_messages = [self._convert_message(message) for message in messages]
        try:
            response = self._client.create_chat_completion(
                model=self._resolve_model(),
                messages=payload_messages,
                temperature=self._config.generate_temperature,
                top_p=self._config.generate_top_p,
                top_k=self._config.generate_top_k,
                max_tokens=self._config.generate_max_tokens,
                functions=self._build_function_definitions(tools),
            )
        except OpenAIClientError as error:
            raise self._wrap_exception(error) from error

        choice = self._parse_choice(response)
        tool_calls = self._extract_tool_calls(choice)
        text = choice.get("content") or ""
        return LLMResponse(
            text=text,
            model=self._resolve_model(),
            raw=response,
            metrics=None,
            tool_calls=tool_calls,
        )

    def generate(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        stream_handler: PartialCallback | None = None,
    ) -> LLMResponse:
        if not messages:
            return LLMResponse(text="No input provided", model=self.provider_name(), raw=None, metrics=None)
        return self._handle_chat(messages=messages, tools=tools, stream_handler=stream_handler)

    def ensure_model_available(self, on_progress: ProgressCallback | None = None) -> str | None:
        return self._resolve_model()
