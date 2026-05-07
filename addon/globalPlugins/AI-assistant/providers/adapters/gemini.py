# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
from collections.abc import Callable
from typing import Any, Optional

from logHandler import log

from ...core.canonical import Message, Tool
from ...core.tooling import ToolCall
from ...core.messages import LLMResponse, SummaryResponse
from ...gemini import GeminiAPIError, GeminiClient, GeminiClientError
from ...gemini.types import Content, GenerateContentConfig, Part
from ..config import GeminiConfig
from ..interfaces import (
	LLMProvider,
	LLMProviderError,
	MissingCredentialsError,
	MissingEndpointError,
	MissingModelError,
	PartialCallback,
	ProviderModelInfo,
	SamplingDefaults,
	UnsupportedModelError,
)
from ...service.provider_readiness import is_gemini_generate_content_incompatible_model_name
from ...tools import build_function_tool_definition, normalize_tool_calls


class GeminiProvider(LLMProvider):
	def __init__(self, config: GeminiConfig) -> None:
		self._config = config
		self._validate_config(config)
		try:
			self._client = GeminiClient(
				api_key=config.api_key,
				api_token=config.api_token,
				base_url=config.base_url,
				timeout_seconds=config.timeout_seconds,
			)
		except GeminiClientError as error:
			raise LLMProviderError(str(error)) from error

	def _validate_config(self, config: GeminiConfig) -> None:
		if not str(config.model_name or "").strip():
			raise MissingModelError("Gemini model name is required.")
		if not str(config.base_url or "").strip():
			raise MissingEndpointError("Gemini base URL is required.")
		if not str(config.api_key or "").strip() and not str(config.api_token or "").strip():
			raise MissingCredentialsError("Gemini API key or bearer token is required.")

	def provider_name(self) -> str:
		return "gemini"

	def supports_streaming(self) -> bool:
		return True

	def supports_image_description(self) -> bool:
		return True

	def list_models(self) -> tuple[ProviderModelInfo, ...]:
		page_token: str | None = None
		models: list[ProviderModelInfo] = []
		while True:
			response = self._client.list_models(page_size=100, page_token=page_token)
			for model in response.models:
				if not model.name:
					continue
				normalized_model = self._normalize_model_info(model)
				if normalized_model.supports("chat"):
					models.append(normalized_model)
			page_token = response.next_page_token
			if not page_token:
				break
		return tuple(models)

	def get_model_info(self, model_name: str | None = None) -> ProviderModelInfo | None:
		resolved_model = (model_name or self._resolve_model()).strip()
		if not resolved_model:
			return None
		return self._normalize_model_info(self._client.get_model(resolved_model))

	def _normalize_model_info(self, model: Any) -> ProviderModelInfo:
		model_name = str(model.name or "").strip().split("/")[-1]
		capabilities: set[str] = set()
		methods = tuple(method for method in model.supported_generation_methods or [] if isinstance(method, str))
		if methods:
			capabilities.update(("completion", "text_input", "text_output"))
		if "generateContent" in methods:
			capabilities.update(("chat", "tools"))
		if "streamGenerateContent" in methods:
			capabilities.add("streaming")
		if model.thinking:
			capabilities.add("thinking")
		if methods and "embedContent" not in methods:
			capabilities.add("image_input")

		return ProviderModelInfo(
			id=model_name,
			provider=self.provider_name(),
			display_name=model.display_name or model_name,
			description=model.description,
			context_window=model.input_token_limit,
			output_token_limit=model.output_token_limit,
			capabilities=tuple(sorted(capabilities)),
			sampling_defaults=SamplingDefaults(
				temperature=model.temperature,
				top_p=model.top_p,
				top_k=model.top_k,
				extra={"max_temperature": model.max_temperature} if model.max_temperature is not None else {},
			),
			raw=dict(model.raw),
		)

	def _resolve_model(self) -> str:
		model = self._config.model_name
		if not model:
			raise MissingModelError("Gemini model name is required.")
		resolved = model.strip()
		if is_gemini_generate_content_incompatible_model_name(resolved):
			raise UnsupportedModelError(
				"The selected Gemini model is only available through another Gemini API workflow and cannot be used for chat or summaries here. Choose a standard Gemini model that supports generateContent.",
			)
		return resolved

	def _wrap_gemini_error(self, error: GeminiClientError) -> LLMProviderError:
		if isinstance(error, GeminiAPIError):
			message = str(getattr(error, "details", "") or getattr(error, "body", "") or "")
			if (
				error.status_code == 404 and "not supported for generatecontent" in message.lower()
			) or (
				error.status_code == 400 and "only supports interactions api" in message.lower()
			):
				return UnsupportedModelError(
					"The selected Gemini model does not support this add-on's generateContent workflow. Choose a standard Gemini model instead of a Live API or Interactions-only preview model."
				)
		return LLMProviderError(str(error))

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
			raise self._wrap_gemini_error(error) from error
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
			raise self._wrap_gemini_error(error) from error
		return SummaryResponse(text=response.text, model=model, provider=self.provider_name())

	def _build_generation_config(self) -> GenerateContentConfig:
		return GenerateContentConfig(
			temperature=self._config.generate_temperature,
			top_p=self._config.generate_top_p,
			top_k=self._config.generate_top_k,
		)

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
		return {"functionDeclarations": [build_function_tool_definition(tool)["function"]]}

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
			normalized = normalize_tool_calls(tool_calls)
			log.debug("GeminiProvider._extract_tool_calls: extracted top-level tool_calls=%s", [tc.name for tc in normalized] if normalized else None)
			return normalized

		candidates = raw_response.get("candidates")
		if isinstance(candidates, list):
			for candidate in candidates:
				if not isinstance(candidate, dict):
					continue
				content = candidate.get("content")
				if isinstance(content, dict):
					if content.get("type") == "function_call":
						normalized = normalize_tool_calls([content])
						log.debug("GeminiProvider._extract_tool_calls: extracted function_call candidate=%s", [tc.name for tc in normalized] if normalized else None)
						return normalized
					if content.get("type") == "tool_call":
						normalized = normalize_tool_calls([content])
						log.debug("GeminiProvider._extract_tool_calls: extracted tool_call candidate=%s", [tc.name for tc in normalized] if normalized else None)
						return normalized
					function_call = content.get("function_call") or content.get("tool_call")
					if isinstance(function_call, dict):
						normalized = normalize_tool_calls([function_call])
						log.debug("GeminiProvider._extract_tool_calls: extracted nested function_call/tool_call=%s", [tc.name for tc in normalized] if normalized else None)
						return normalized
					parts = content.get("parts")
					if isinstance(parts, list):
						for part in parts:
							if not isinstance(part, dict):
								continue
							function_call = part.get("function_call") or part.get("tool_call") or part.get("functionCall")
							if isinstance(function_call, dict):
								normalized = normalize_tool_calls([function_call])
								log.debug("GeminiProvider._extract_tool_calls: extracted part-level functionCall=%s", [tc.name for tc in normalized] if normalized else None)
								return normalized

		log.debug("GeminiProvider._extract_tool_calls: no tool calls found")
		return None

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

		try:
			response = self._client.generate_content(
			model=self._resolve_model(),
			contents=contents,
			config=self._build_generation_config(),
			tools=gemini_tools,
			system_instruction=system_instruction,
			)
		except GeminiClientError as error:
			raise self._wrap_gemini_error(error) from error
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
		return self._handle_chat(messages, tools, stream_handler)

	def ensure_model_available(self, on_progress: Callable[[str], None] | None = None) -> str | None:
		model = self._resolve_model()
		if on_progress is not None:
			on_progress(f"Gemini model {model or 'unknown'} is ready.")
		return model
