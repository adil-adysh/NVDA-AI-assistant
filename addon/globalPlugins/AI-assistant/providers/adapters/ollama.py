# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
from typing import Any

from logHandler import log

from ...core.canonical import Message, Tool
from ...core.tooling import ToolCall
from ...core.messages import LLMResponse, SummaryResponse
from ...ollama import OllamaClient, OllamaClientError
from ..config import OllamaConfig
from ..interfaces import LLMProvider, LLMProviderError, PartialCallback, ProgressCallback
from ...tools import build_function_tool_definition, normalize_tool_calls


class OllamaProvider(LLMProvider):
	def __init__(self, config: OllamaConfig) -> None:
		self._config = config
		try:
			self._client = OllamaClient(
				baseURL=config.server_url,
				model=config.model_name,
				timeoutSeconds=config.timeout_seconds,
			)
		except OllamaClientError as error:
			raise self._wrap_exception(error) from error

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

	def _convert_tool(self, tool: Tool) -> dict[str, Any]:
		return build_function_tool_definition(tool)

	def _handle_chat(self, messages: list[Message], tools: list[Tool] | None, stream_handler: PartialCallback | None) -> LLMResponse:
		if not messages:
			return LLMResponse(text="No input provided", model=self.provider_name(), raw=None, metrics=None)

		chat_messages: list[dict[str, Any]] = []
		for msg in messages:
			chat_message: dict[str, Any] = {"role": msg.role}
			text_parts: list[str] = []
			tool_name: str | None = None
			tool_calls: list[dict[str, Any]] = []

			for part in msg.parts:
				if part.type == "text" and part.text is not None:
					text_parts.append(part.text)
				elif part.type == "image" and part.image is not None:
					chat_message.setdefault("images", []).append(base64.b64encode(part.image).decode("ascii"))
				elif part.type == "tool_call":
					tool_name = part.tool_name or tool_name
					tool_calls.append({"name": part.tool_name or "", "arguments": part.tool_args or {}})
				elif part.type == "tool_result":
					tool_name = part.tool_name or tool_name
					chat_message["content"] = part.tool_result if part.tool_result is not None else part.text or ""

			if text_parts:
				chat_message["content"] = "\n".join(text_parts)
			if tool_name:
				chat_message["tool_name"] = tool_name
			if tool_calls:
				chat_message["tool_calls"] = tool_calls

			chat_messages.append(chat_message)

		log.debug(
			"OllamaProvider._handle_chat: canonical_messages=%s tools=%s",
			[(msg.role, [part.type for part in msg.parts]) for msg in messages],
			[tool.name for tool in tools] if tools else None,
		)
		log.debug("OllamaProvider._handle_chat: sending messages=%s", chat_messages)

		try:
			response = self._client.chat(
				chat_messages,
				tools=[self._convert_tool(tool) for tool in tools] if tools else None,
				onPartial=stream_handler,
			)
		except OllamaClientError as error:
			log.debug("OllamaProvider._handle_chat: chat request failed: %s", error)
			raise self._wrap_exception(error) from error

		tool_calls = self._extract_tool_calls(response.metadata if response.metadata else {})
		log.debug(
			"OllamaProvider._handle_chat: provider returned text_len=%d tool_calls=%s raw=%s",
			len(response.text or ""),
			[tc.name for tc in tool_calls] if tool_calls else None,
			response.metadata,
		)

		return LLMResponse(
			text=response.text,
			model=response.model,
			raw=response,
			metrics=None,
			tool_calls=tool_calls,
		)

	def _extract_tool_calls(self, metadata: dict[str, Any]) -> list[ToolCall] | None:
		log.debug("OllamaProvider._extract_tool_calls: metadata=%s", metadata)
		raw_response = metadata.get("raw") if isinstance(metadata, dict) else None
		if not isinstance(raw_response, dict):
			log.debug("OllamaProvider._extract_tool_calls: raw response is not a dict")
			return None

		message = raw_response.get("message") if isinstance(raw_response.get("message"), dict) else raw_response
		tool_calls = message.get("tool_calls") or message.get("toolCalls") or raw_response.get("tool_calls")
		if isinstance(tool_calls, list):
			normalized = normalize_tool_calls(tool_calls)
			log.debug("OllamaProvider._extract_tool_calls: normalized tool_calls=%s", [tc.name for tc in normalized] if normalized else None)
			return normalized

		function_call = None
		if isinstance(message, dict):
			function_call = message.get("function_call") or message.get("tool_call")
		if isinstance(function_call, dict):
			normalized = normalize_tool_calls([function_call])
			log.debug("OllamaProvider._extract_tool_calls: normalized single function_call=%s", [tc.name for tc in normalized] if normalized else None)
			return normalized

		log.debug("OllamaProvider._extract_tool_calls: no tool calls found")
		return None

	def _handle_chat_fallback(self, messages: list[Message]) -> LLMResponse:
		plain_text = "\n".join(
			"".join(part.text or "" for part in msg.parts if part.type == "text")
			for msg in messages
		)
		result = self.summarize(plain_text)
		return LLMResponse(text=result.text, model=result.model, raw=result, metrics=None)

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
		def progress_adapter(event: dict[str, Any]) -> None:
			if on_progress is None:
				return
			status = event.get("status") or event.get("message") or event.get("error")
			on_progress(str(status or event))

		try:
			return self._client.ensureModelInstalled(onProgress=progress_adapter if on_progress else None)
		except OllamaClientError as error:
			raise self._wrap_exception(error) from error
