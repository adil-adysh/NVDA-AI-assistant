# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import json
from collections.abc import Iterable
from typing import Any

from ...core.canonical import Message, Tool
from ...core.messages import LLMResponse, SummaryResponse
from ...core.tooling import ToolCall
from ...openai import OpenAIClient, OpenAIClientError
from ...tools import build_function_tool_definition, normalize_tool_calls
from ..config import OpenAIConfig
from ..interfaces import LLMProvider, LLMProviderError, PartialCallback, ProgressCallback, ProviderModelInfo, SamplingDefaults


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
        return self._capabilities_for_model(self._resolve_model()).supports("streaming")

    def supports_image_description(self) -> bool:
        return self._capabilities_for_model(self._resolve_model()).supports("image_input")

    def _wrap_exception(self, error: Exception) -> LLMProviderError:
        if isinstance(error, LLMProviderError):
            return error
        return LLMProviderError(str(error))

    def _resolve_model(self) -> str:
        model = self._config.model_name
        if not model:
            raise LLMProviderError("OpenAI model name is required.")
        return model.strip()

    def list_models(self) -> tuple[ProviderModelInfo, ...]:
        try:
            response = self._client.list_models()
        except OpenAIClientError as error:
            if self._should_fallback_to_configured_model(error):
                return (self._capabilities_for_model(self._resolve_model()),)
            raise self._wrap_exception(error) from error

        models = response.get("data")
        if not isinstance(models, list):
            return ()

        return tuple(
            self._normalize_model_info(item)
            for item in models
            if isinstance(item, dict) and str(item.get("id", "")).strip()
        )

    def get_model_info(self, model_name: str | None = None) -> ProviderModelInfo | None:
        resolved_model = (model_name or self._resolve_model()).strip()
        if not resolved_model:
            return None
        try:
            response = self._client.get_model(resolved_model)
        except OpenAIClientError as error:
            if self._should_fallback_to_configured_model(error):
                return self._capabilities_for_model(resolved_model)
            raise self._wrap_exception(error) from error
        return self._normalize_model_info(response)

    def _should_fallback_to_configured_model(self, error: OpenAIClientError) -> bool:
        if getattr(error, "status_code", None) != 404:
            return False
        path = str(getattr(error, "path", "") or "")
        return "/models" in path

    def _capabilities_for_model(self, model_name: str) -> ProviderModelInfo:
        return self._normalize_model_info({"id": model_name})

    def _normalize_model_info(self, data: dict[str, Any]) -> ProviderModelInfo:
        model_id = str(data.get("id", "")).strip()
        lowered = self._normalized_model_family(model_id)
        capabilities: set[str] = set()
        sampling_defaults = SamplingDefaults(temperature=1.0, top_p=1.0)
        input_modalities = self._extract_modalities(data, modality_kind="input")
        output_modalities = self._extract_modalities(data, modality_kind="output")

        if lowered:
            capabilities.add("streaming")

        if any(token in lowered for token in ("gpt", "chatgpt", "o1", "o3", "o4")):
            capabilities.update(("chat", "completion", "tools", "text_input", "text_output"))

        if lowered.startswith(("gpt-5", "o1", "o3", "o4")):
            capabilities.add("thinking")

        if self._supports_image_input_family(lowered):
            capabilities.add("image_input")

        if lowered.startswith(("gpt-audio", "gpt-realtime")):
            capabilities.update(("audio_input", "audio_output"))

        if lowered.startswith("gpt-realtime"):
            capabilities.add("realtime")

        if lowered.startswith("gpt-image"):
            capabilities.add("image_output")

        if lowered.endswith(("transcribe", "transcription")):
            capabilities.add("audio_input")

        capabilities.update(self._capabilities_from_modalities(input_modalities, modality_kind="input"))
        capabilities.update(self._capabilities_from_modalities(output_modalities, modality_kind="output"))

        return ProviderModelInfo(
            id=model_id,
            provider=self.provider_name(),
            display_name=model_id or None,
            owned_by=str(data.get("owned_by", "")).strip() or None,
            created=data.get("created") if isinstance(data.get("created"), int) else None,
            capabilities=tuple(sorted(capabilities)),
            sampling_defaults=sampling_defaults,
            raw=data,
        )

    def _normalized_model_family(self, model_id: str) -> str:
        lowered = model_id.lower().strip()
        if lowered.startswith("ft:"):
            parts = lowered.split(":")
            if len(parts) > 1 and parts[1]:
                return parts[1]
        return lowered

    def _supports_image_input_family(self, lowered_model: str) -> bool:
        return lowered_model.startswith(
            (
                "chatgpt-4o",
                "gpt-4o",
                "gpt-4.1",
                "gpt-4.5",
                "gpt-5",
                "gpt-4-turbo",
                "gpt-4-vision-preview",
                "o1",
                "o3",
                "o4",
            )
        )

    def _extract_modalities(self, data: dict[str, Any], modality_kind: str) -> tuple[str, ...]:
        key = f"{modality_kind}_modalities"
        modalities = self._coerce_modalities(data.get(key))
        if modalities:
            return modalities

        architecture = data.get("architecture")
        if isinstance(architecture, dict):
            modalities = self._coerce_modalities(architecture.get(key))
            if modalities:
                return modalities

        return ()

    def _coerce_modalities(self, value: Any) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple, set)):
            return ()
        normalized = tuple(
            str(item).strip().lower()
            for item in value
            if isinstance(item, str) and str(item).strip()
        )
        return tuple(dict.fromkeys(normalized))

    def _capabilities_from_modalities(self, modalities: tuple[str, ...], modality_kind: str) -> set[str]:
        capabilities: set[str] = set()
        if "text" in modalities:
            capabilities.add(f"text_{modality_kind}")
        if "image" in modalities:
            capabilities.add(f"image_{modality_kind}")
        if "audio" in modalities:
            capabilities.add(f"audio_{modality_kind}")
        return capabilities

    def summarize(self, prompt: str, stream_handler: PartialCallback | None = None) -> SummaryResponse:
        model = self._resolve_model()
        try:
            if stream_handler is not None:
                text, _, _ = self._stream_chat_completion(
                    model=model,
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant that summarizes text concisely."},
                        {"role": "user", "content": prompt},
                    ],
                    stream_handler=stream_handler,
                )
                return SummaryResponse(text=text, model=model, provider=self.provider_name())

            response = self._client.create_chat_completion(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that summarizes text concisely."},
                    {"role": "user", "content": prompt},
                ],
                temperature=self._config.generate_temperature,
                top_p=self._config.generate_top_p,
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
        model = self._resolve_model()
        if not self._capabilities_for_model(model).supports("image_input"):
            raise LLMProviderError(f"OpenAI model {model} does not advertise image input support.")

        try:
            if stream_handler is not None:
                text, _, _ = self._stream_describe_image(
                    model=model,
                    image_base64=image_base64,
                    prompt=prompt,
                    stream_handler=stream_handler,
                )
                return SummaryResponse(text=text, model=model, provider=self.provider_name())

            response = self._client.describe_image(
                model=model,
                image_base64=image_base64,
                prompt=prompt,
                temperature=self._config.generate_temperature,
                top_p=self._config.generate_top_p,
                max_tokens=self._config.generate_max_tokens,
            )
        except OpenAIClientError as error:
            raise self._wrap_exception(error) from error

        choice = self._parse_choice(response)
        return SummaryResponse(text=choice.get("content", "") or "", model=model, provider=self.provider_name())

    def _stream_describe_image(
        self,
        model: str,
        image_base64: str,
        prompt: str,
        stream_handler: PartialCallback,
    ) -> tuple[str, list[ToolCall] | None, list[dict[str, Any]]]:
        return self._collect_stream_completion(
            self._client.stream_describe_image(
                model=model,
                image_base64=image_base64,
                prompt=prompt,
                temperature=self._config.generate_temperature,
                top_p=self._config.generate_top_p,
                max_tokens=self._config.generate_max_tokens,
            ),
            stream_handler,
        )

    def _collect_stream_completion(
        self,
        chunks: Iterable[dict[str, Any]],
        stream_handler: PartialCallback,
    ) -> tuple[str, list[ToolCall] | None, list[dict[str, Any]]]:
        accumulated_text = ""
        collected_chunks: list[dict[str, Any]] = []
        streamed_tool_calls: dict[int, dict[str, Any]] = {}

        for chunk in chunks:
            collected_chunks.append(chunk)
            choices = chunk.get("choices")
            if not isinstance(choices, list):
                continue
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                delta = choice.get("delta")
                if not isinstance(delta, dict):
                    continue

                content = delta.get("content")
                if isinstance(content, str) and content:
                    accumulated_text = f"{accumulated_text}{content}"
                    stream_handler(accumulated_text, len(accumulated_text))

                self._merge_streamed_tool_calls(streamed_tool_calls, delta.get("tool_calls"))

                function_call = delta.get("function_call")
                if isinstance(function_call, dict):
                    self._merge_streamed_tool_calls(
                        streamed_tool_calls,
                        [
                            {
                                "index": 0,
                                "function": function_call,
                            }
                        ],
                    )

        normalized_tool_calls = normalize_tool_calls(
            [streamed_tool_calls[index] for index in sorted(streamed_tool_calls)]
        )
        return accumulated_text, normalized_tool_calls, collected_chunks

    def _convert_message(self, message: Message) -> dict[str, Any]:
        text_parts: list[str] = []
        content_parts: list[dict[str, Any]] = []
        for part in message.parts:
            if part.type == "text" and part.text is not None:
                text_parts.append(part.text)
                content_parts.append({"type": "text", "text": part.text})
            elif part.type == "tool_result":
                if part.tool_result is not None:
                    text = json.dumps(part.tool_result)
                elif part.text is not None:
                    text = part.text
                else:
                    text = ""
                text_parts.append(text)
                content_parts.append({"type": "text", "text": text})
            elif part.type == "image":
                if part.image is not None:
                    image_base64 = base64.b64encode(part.image).decode("ascii")
                    content_parts.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_base64}"},
                        }
                    )
                    text_parts.append("[IMAGE ATTACHED]")
            elif part.type == "tool_call":
                rendered = f"[tool call: {part.tool_name or 'unknown'} arguments={json.dumps(part.tool_args or {})}]"
                text_parts.append(rendered)
                content_parts.append({"type": "text", "text": rendered})

        if message.role == "tool":
            return {
                "role": message.role,
                "content": "\n".join(text_parts) if text_parts else "",
            }

        return {
            "role": message.role,
            "content": content_parts if any(part.get("type") == "image_url" for part in content_parts) else "\n".join(text_parts),
        }

    def _build_tool_definitions(self, tools: list[Tool] | None) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        return [build_function_tool_definition(tool) for tool in tools]

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
        tool_calls = choice.get("tool_calls")
        if isinstance(tool_calls, list):
            return normalize_tool_calls(tool_calls)

        function_call = choice.get("function_call")
        if isinstance(function_call, dict):
            return normalize_tool_calls([{"function": function_call}])
        return None

    def _stream_chat_completion(
        self,
        model: str,
        messages: list[dict[str, Any]],
        stream_handler: PartialCallback,
        tools: list[dict[str, Any]] | None = None,
    ) -> tuple[str, list[ToolCall] | None, list[dict[str, Any]]]:
        return self._collect_stream_completion(
            self._client.stream_chat_completion(
                model=model,
                messages=messages,
                temperature=self._config.generate_temperature,
                top_p=self._config.generate_top_p,
                max_tokens=self._config.generate_max_tokens,
                tools=tools,
            ),
            stream_handler,
        )

    def _merge_streamed_tool_calls(
        self,
        streamed_tool_calls: dict[int, dict[str, Any]],
        payload: Any,
    ) -> None:
        if not isinstance(payload, list):
            return

        for item in payload:
            if not isinstance(item, dict):
                continue
            index = item.get("index")
            if not isinstance(index, int):
                continue
            target = streamed_tool_calls.setdefault(index, {"type": "function", "function": {"name": "", "arguments": ""}})
            if isinstance(item.get("id"), str):
                target["id"] = item["id"]
            if isinstance(item.get("type"), str):
                target["type"] = item["type"]

            function_payload = item.get("function")
            if not isinstance(function_payload, dict):
                continue

            target_function = target.setdefault("function", {})
            if isinstance(function_payload.get("name"), str):
                target_function["name"] = f"{target_function.get('name', '')}{function_payload['name']}"
            if isinstance(function_payload.get("arguments"), str):
                target_function["arguments"] = (
                    f"{target_function.get('arguments', '')}{function_payload['arguments']}"
                )

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
            if stream_handler is not None:
                text, tool_calls, chunks = self._stream_chat_completion(
                    model=self._resolve_model(),
                    messages=payload_messages,
                    stream_handler=stream_handler,
                    tools=self._build_tool_definitions(tools),
                )
                return LLMResponse(
                    text=text,
                    model=self._resolve_model(),
                    raw={"chunks": chunks, "stream": True},
                    metrics=None,
                    tool_calls=tool_calls,
                )

            response = self._client.create_chat_completion(
                model=self._resolve_model(),
                messages=payload_messages,
                temperature=self._config.generate_temperature,
                top_p=self._config.generate_top_p,
                max_tokens=self._config.generate_max_tokens,
                tools=self._build_tool_definitions(tools),
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
