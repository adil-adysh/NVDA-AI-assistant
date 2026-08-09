# -*- coding: utf-8 -*-
"""Unified OpenAI-compatible provider adapter.

Wraps ``llm_client.OpenAiClient`` (Rust PyO3 extension) to implement the
``LLMProvider`` ABC.  Supports any server that speaks the OpenAI
``/v1/chat/completions`` and ``/v1/models`` protocol — Ollama, OpenAI, Gemini
OpenAI-compat, LiteRT, llama.cpp server, etc.

Model listing uses a **hybrid** strategy:
1. Try Ollama-native ``GET /api/tags`` for rich metadata (capabilities,
   context_window, parameter_size).
2. Fall back to ``GET /v1/models`` + name-based capability inference for
   non-Ollama backends.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

from logHandler import log

from ...core.canonical import Message, Tool
from ...core.messages import LLMResponse, SummaryResponse
from ...core.tooling import ToolCall
from ...tools import build_function_tool_definition, normalize_tool_calls
from ..config import OpenAICompatConfig
from ..endpoints import EndpointConfigurationError, resolve_openai_endpoints
from ..interfaces import (
	LLMProvider,
	LLMProviderError,
	MissingModelError,
	PartialCallback,
	ProgressCallback,
	ProviderModelInfo,
	SamplingDefaults,
)

try:
	import llm_client  # type: ignore[import-untyped]
except ImportError:
	llm_client = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Capability inference helpers
# ---------------------------------------------------------------------------

# Model name tokens that indicate image-input support (Ollama models).
_OLLAMA_VISION_TOKENS = (
	"llava",
	"vision",
	"moondream",
	"bakllava",
	"minicpm-v",
)

# OpenAI model families that support image input.
_OPENAI_VISION_FAMILIES = (
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

# OpenAI model families that support thinking/reasoning.
_OPENAI_THINKING_FAMILIES = ("gpt-5", "o1", "o3", "o4")

# Streaming engines can deliver a large burst of already-buffered SSE events.
# Keep UI callbacks useful without allowing a worker to monopolize the GIL and
# starve NVDA's main event loop.
_STREAM_CALLBACK_MIN_CHARS = 128
_STREAM_CALLBACK_MIN_INTERVAL = 0.05
_STREAM_COOPERATIVE_YIELD_INTERVAL = 0.01

# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class OpenAICompatProvider(LLMProvider):
	"""LLM provider backed by the Rust ``llm_client`` extension."""

	def __init__(self, config: OpenAICompatConfig) -> None:
		if llm_client is None:
			raise LLMProviderError(
				"llm_client Rust extension is not installed. Rebuild with: python scripts/build.py"
			)

		self._config = config
		self._provider_id = str(config.provider or "").strip() or "openai_compat"
		try:
			self._endpoints = resolve_openai_endpoints(
				config.base_url,
				config.chat_path,
				config.models_path,
			)
		except EndpointConfigurationError as exc:
			raise LLMProviderError(str(exc)) from exc

		# Main client uses explicitly resolved endpoints. This supports API
		# roots such as /v1, Gemini's /v1beta/openai, and custom gateways.
		self._client = llm_client.OpenAiClient(
			base_url=self._endpoints.service_url,
			api_key=config.api_key or "",
			timeout_seconds=config.timeout_seconds,
			chat_url=self._endpoints.chat_url,
			models_url=self._endpoints.models_url,
		)

		# Lazy native client for Ollama-specific endpoints (/api/tags, /api/chat).
		self._native_base_url = self._endpoints.service_url.rstrip("/").removesuffix("/v1")
		self._native_client_cache: Any = None
		self._is_ollama: bool | None = None  # tri-state: None = not probed yet

	# ------------------------------------------------------------------
	# ABC — identity
	# ------------------------------------------------------------------

	def provider_name(self) -> str:
		return self._provider_id

	def supports_streaming(self) -> bool:
		return True

	def supports_image_description(self) -> bool:
		return self._detect_ollama() or self._model_supports_images(self._resolve_model())

	# ------------------------------------------------------------------
	# ABC — model listing (hybrid)
	# ------------------------------------------------------------------

	def list_models(self) -> tuple[ProviderModelInfo, ...]:
		# 1. Try Ollama-native /api/tags for rich metadata.
		if self._detect_ollama():
			return self._list_models_ollama_native()

		# 2. Fall back to /v1/models + name inference.
		return self._list_models_openai_compat()

	def get_model_info(self, model_name: str | None = None) -> ProviderModelInfo | None:
		resolved = (model_name or self._resolve_model()).strip()
		if not resolved:
			return None

		# Ollama-native: look up by name in /api/tags.
		if self._detect_ollama():
			info = self._get_model_info_ollama_native(resolved)
			if info is not None:
				return info

		# OpenAI-compat fallback: name-based inference.
		models = self._list_models_openai_compat()
		for m in models:
			if m.id == resolved:
				return m
		return self._capabilities_for_model(resolved)

	# ------------------------------------------------------------------
	# ABC — summarise / describe
	# ------------------------------------------------------------------

	def summarize(
		self,
		prompt: str,
		stream_handler: PartialCallback | None = None,
	) -> SummaryResponse:
		model = self._resolve_model()
		messages: list[dict[str, Any]] = [
			{
				"role": "system",
				"content": "You are a helpful assistant that summarizes text concisely.",
			},
			{"role": "user", "content": prompt},
		]

		if stream_handler is not None:
			text, _, _ = self._stream_chat(model, messages, stream_handler)
			return SummaryResponse(text=text, model=model, provider=self.provider_name())

		response = self._client.chat_completion(
			model=model,
			messages=messages,
			temperature=self._config.generate_temperature,
			top_p=self._config.generate_top_p,
			max_tokens=self._config.generate_max_tokens,
			num_ctx=self._config.num_ctx,
		)
		choice = self._parse_choice(response)
		return SummaryResponse(
			text=choice.get("content", ""),
			model=model,
			provider=self.provider_name(),
		)

	def describe_image(
		self,
		image_base64: str,
		prompt: str,
		stream_handler: PartialCallback | None = None,
	) -> SummaryResponse:
		model = self._resolve_model()

		if self._detect_ollama():
			return self._describe_image_ollama(model, image_base64, prompt, stream_handler)

		return self._describe_image_openai_compat(model, image_base64, prompt, stream_handler)

	# ------------------------------------------------------------------
	# ABC — chat / generate
	# ------------------------------------------------------------------

	def generate(
		self,
		messages: list[Message],
		tools: list[Tool] | None = None,
		stream_handler: PartialCallback | None = None,
	) -> LLMResponse:
		if not messages:
			return LLMResponse(
				text="No input provided",
				model=self.provider_name(),
				raw=None,
				metrics=None,
			)

		if self._detect_ollama() and self._has_image_parts(messages):
			return self._generate_ollama_multimodal(messages, tools, stream_handler)

		return self._generate_openai_compat(messages, tools, stream_handler)

	def ensure_model_available(self, on_progress: ProgressCallback | None = None) -> str | None:
		model = self._resolve_model()
		if on_progress is not None:
			on_progress(f"Model {model or 'unknown'} is ready.")
		return model

	# ==================================================================
	# Internal: model listing
	# ==================================================================

	def _detect_ollama(self) -> bool:
		"""Probe whether the server is Ollama (cached after first call)."""
		if self._is_ollama is not None:
			return self._is_ollama
		try:
			self._native_client().get("/api/tags")
			self._is_ollama = True
		except Exception:
			self._is_ollama = False
		return self._is_ollama

	def _native_client(self) -> Any:
		"""Lazy-initialised client pointed at the Ollama-native base URL."""
		if self._native_client_cache is None:
			if llm_client is None:
				raise LLMProviderError("llm_client extension not available")
			self._native_client_cache = llm_client.OpenAiClient(
				base_url=self._native_base_url,
				api_key="",
				timeout_seconds=self._config.timeout_seconds,
			)
		return self._native_client_cache

	def _list_models_ollama_native(self) -> tuple[ProviderModelInfo, ...]:
		"""List models via Ollama-native GET /api/tags."""
		try:
			data = self._native_client().get("/api/tags")
		except Exception as exc:
			log.debug("OpenAICompatProvider: /api/tags failed: %s", exc)
			return ()

		models_list = data.get("models") if isinstance(data, dict) else None
		if not isinstance(models_list, list):
			return ()

		result: list[ProviderModelInfo] = []
		for item in models_list:
			if not isinstance(item, dict):
				continue
			name = str(item.get("name", "")).strip()
			if not name:
				continue
			result.append(self._normalize_ollama_model(item))
		return tuple(result)

	def _get_model_info_ollama_native(self, model_name: str) -> ProviderModelInfo | None:
		"""Look up a single model via Ollama-native /api/tags."""
		for info in self._list_models_ollama_native():
			if info.id == model_name:
				return info
		return None

	def _normalize_ollama_model(self, data: dict[str, Any]) -> ProviderModelInfo:
		name = str(data.get("name", "")).strip()
		details = data.get("details") if isinstance(data.get("details"), dict) else {}
		capabilities = {
			"completion",
			"chat",
			"streaming",
			"text_input",
			"text_output",
			"tools",
		}

		lowered = name.lower()
		if any(token in lowered for token in _OLLAMA_VISION_TOKENS):
			capabilities.add("image_input")
		if self._config.think:
			capabilities.add("thinking")

		family = str(details.get("family", "")).strip().lower()
		if family and family not in lowered:
			lowered_family = family
			if any(t in lowered_family for t in _OLLAMA_VISION_TOKENS):
				capabilities.add("image_input")

		context_window = None
		if isinstance(details.get("context_length"), int):
			context_window = details["context_length"]

		return ProviderModelInfo(
			id=name,
			provider=self.provider_name(),
			display_name=name,
			description=str(data.get("description", "")).strip() or None,
			context_window=context_window,
			capabilities=tuple(sorted(capabilities)),
			sampling_defaults=SamplingDefaults(),
			raw=data,
		)

	def _list_models_openai_compat(self) -> tuple[ProviderModelInfo, ...]:
		"""List models via OpenAI-compat GET /v1/models + name inference."""
		try:
			models = self._client.list_models()
		except Exception as exc:
			log.debug("OpenAICompatProvider: /v1/models failed: %s", exc)
			return ()

		if not isinstance(models, list):
			return ()

		result: list[ProviderModelInfo] = []
		for item in models:
			if not isinstance(item, dict):
				continue
			model_id = str(item.get("id", "")).strip()
			if not model_id:
				continue
			result.append(self._capabilities_for_model(model_id))
		return tuple(result)

	def _capabilities_for_model(self, model_id: str) -> ProviderModelInfo:
		"""Build ProviderModelInfo with name-based capability inference."""
		lowered = model_id.lower().strip()
		capabilities: set[str] = {"completion", "text_input", "text_output"}

		# Nearly everything supports chat + streaming.
		capabilities.update(("chat", "streaming"))

		# ── LiteRT model detection (must run before generic patterns) ──
		litert_def = self._lookup_litert_model(model_id)
		if litert_def is not None:
			if litert_def.vision:
				capabilities.add("image_input")
			if litert_def.thinking:
				capabilities.add("thinking")
			if litert_def.mtp:
				capabilities.add("mtp")
			capabilities.add("tools")

		# GPT/OpenAI family.
		if any(t in lowered for t in ("gpt", "chatgpt", "o1", "o3", "o4")):
			capabilities.add("tools")
		if lowered.startswith(_OPENAI_THINKING_FAMILIES):
			capabilities.add("thinking")
		if lowered.startswith(_OPENAI_VISION_FAMILIES):
			capabilities.add("image_input")

		# Generic image-input detection for non-OpenAI models.
		if any(t in lowered for t in _OLLAMA_VISION_TOKENS):
			capabilities.add("image_input")

		# Gemini models.
		if "gemini" in lowered:
			capabilities.update(("tools", "image_input"))

		# LiteRT .litertlm filename pattern (fallback if lookup missed).
		if litert_def is None and (lowered.endswith(".litertlm") or "litert-community/" in lowered):
			capabilities.add("tools")

		# Gemma models may support vision (generic catch for unknown Gemma variants).
		if litert_def is None and "gemma" in lowered:
			capabilities.add("image_input")

		return ProviderModelInfo(
			id=model_id,
			provider=self.provider_name(),
			display_name=model_id,
			capabilities=tuple(sorted(capabilities)),
			sampling_defaults=SamplingDefaults(temperature=1.0, top_p=1.0),
		)

	@staticmethod
	def _lookup_litert_model(model_id: str) -> object | None:
		"""Try to resolve *model_id* against the known LiteRT model catalog.

		Returns a ``LiteRTModelDef`` or ``None``.
		"""
		try:
			from ..litert_models import lookup_model  # type: ignore[attr-defined]
		except ImportError:
			return None
		return lookup_model(model_id)

	# ==================================================================
	# Internal: image description
	# ==================================================================

	def _describe_image_ollama(
		self,
		model: str,
		image_base64: str,
		prompt: str,
		stream_handler: PartialCallback | None,
	) -> SummaryResponse:
		"""Describe an image via Ollama-native POST /api/chat."""
		payload: dict[str, Any] = {
			"model": model,
			"messages": [
				{
					"role": "user",
					"content": prompt,
					"images": [image_base64],
				}
			],
			"stream": False,
			"options": {"num_ctx": self._config.num_ctx},
		}

		try:
			response = self._native_client().post("/api/chat", payload)
		except Exception as exc:
			raise LLMProviderError(str(exc)) from exc

		message = response.get("message") if isinstance(response, dict) else {}
		text = str(message.get("content", "") or "")
		if stream_handler is not None:
			stream_handler(text, len(text))
		return SummaryResponse(text=text, model=model, provider=self.provider_name())

	def _describe_image_openai_compat(
		self,
		model: str,
		image_base64: str,
		prompt: str,
		stream_handler: PartialCallback | None,
	) -> SummaryResponse:
		"""Describe an image via OpenAI-compat /v1/chat/completions with content arrays."""
		messages: list[dict[str, Any]] = [
			{
				"role": "user",
				"content": [
					{"type": "text", "text": prompt},
					{
						"type": "image_url",
						"image_url": {"url": f"data:image/png;base64,{image_base64}"},
					},
				],
			}
		]

		if stream_handler is not None:
			text, _, _ = self._stream_chat(model, messages, stream_handler)
			return SummaryResponse(text=text, model=model, provider=self.provider_name())

		response = self._client.chat_completion(
			model=model,
			messages=messages,
			temperature=self._config.generate_temperature,
			top_p=self._config.generate_top_p,
			max_tokens=self._config.generate_max_tokens,
			num_ctx=self._config.num_ctx,
		)
		choice = self._parse_choice(response)
		return SummaryResponse(
			text=choice.get("content", ""),
			model=model,
			provider=self.provider_name(),
		)

	# ==================================================================
	# Internal: chat / generate
	# ==================================================================

	def _generate_openai_compat(
		self,
		messages: list[Message],
		tools: list[Tool] | None,
		stream_handler: PartialCallback | None,
	) -> LLMResponse:
		"""Generate via OpenAI-compat /v1/chat/completions."""
		model = self._resolve_model()
		payload_messages = [self._convert_message(msg) for msg in messages]
		tool_defs = self._build_tool_definitions(tools)

		try:
			if stream_handler is not None:
				text, tool_calls, chunks = self._stream_chat(
					model,
					payload_messages,
					stream_handler,
					tools=tool_defs,
				)
				return LLMResponse(
					text=text,
					model=model,
					raw={"chunks": chunks, "stream": True},
					metrics=None,
					tool_calls=tool_calls,
				)

			response = self._client.chat_completion(
				model=model,
				messages=payload_messages,
				tools=tool_defs,
				temperature=self._config.generate_temperature,
				top_p=self._config.generate_top_p,
				max_tokens=self._config.generate_max_tokens,
				num_ctx=self._config.num_ctx,
			)
		except Exception as exc:
			raise LLMProviderError(str(exc)) from exc

		choice = self._parse_choice(response)
		tool_calls = self._extract_tool_calls(choice)
		text = choice.get("content") or ""
		return LLMResponse(
			text=text,
			model=model,
			raw=response,
			metrics=None,
			tool_calls=tool_calls,
		)

	def _generate_ollama_multimodal(
		self,
		messages: list[Message],
		tools: list[Tool] | None,
		stream_handler: PartialCallback | None,
	) -> LLMResponse:
		"""Generate via Ollama-native POST /api/chat (supports images)."""
		model = self._resolve_model()
		ollama_messages: list[dict[str, Any]] = []

		for msg in messages:
			chat_msg: dict[str, Any] = {"role": msg.role}
			text_parts: list[str] = []
			images: list[str] = []

			for part in msg.parts:
				if part.type == "text" and part.text is not None:
					text_parts.append(part.text)
				elif part.type == "image" and part.image is not None:
					images.append(base64.b64encode(part.image).decode("ascii"))
				elif part.type == "tool_result":
					chat_msg["content"] = (
						part.tool_result if part.tool_result is not None else part.text or ""
					)

			if text_parts:
				chat_msg["content"] = "\n".join(text_parts)
			if images:
				chat_msg["images"] = images

			ollama_messages.append(chat_msg)

		payload: dict[str, Any] = {
			"model": model,
			"messages": ollama_messages,
			"stream": False,
			"options": {"num_ctx": self._config.num_ctx},
		}
		if tools:
			payload["tools"] = [build_function_tool_definition(t) for t in tools]

		try:
			response = self._native_client().post("/api/chat", payload)
		except Exception as exc:
			raise LLMProviderError(str(exc)) from exc

		message = response.get("message") if isinstance(response, dict) else {}
		text = str(message.get("content", "") or "")

		tool_calls = self._extract_tool_calls(message)
		if stream_handler is not None:
			stream_handler(text, len(text))

		return LLMResponse(
			text=text,
			model=model,
			raw=response,
			metrics=None,
			tool_calls=tool_calls,
		)

	# ==================================================================
	# Internal: streaming
	# ==================================================================

	def _stream_chat(
		self,
		model: str,
		messages: list[dict[str, Any]],
		stream_handler: PartialCallback,
		tools: list[dict[str, Any]] | None = None,
	) -> tuple[str, list[ToolCall] | None, list[dict[str, Any]]]:
		"""Run a streaming chat completion and collect deltas."""
		accumulated = ""
		chunks: list[dict[str, Any]] = []
		streamed_tool_calls: dict[int, dict[str, Any]] = {}
		reported_chars = 0
		last_callback_at = time.monotonic()
		last_yield_at = last_callback_at

		try:
			for chunk in self._client.chat_completion_stream(
				model=model,
				messages=messages,
				tools=tools,
				temperature=self._config.generate_temperature,
				top_p=self._config.generate_top_p,
				max_tokens=self._config.generate_max_tokens,
				num_ctx=self._config.num_ctx,
			):
				chunks.append(chunk)
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
						accumulated = f"{accumulated}{content}"
						now = time.monotonic()
						if (
							reported_chars == 0
							or len(accumulated) - reported_chars >= _STREAM_CALLBACK_MIN_CHARS
							or now - last_callback_at >= _STREAM_CALLBACK_MIN_INTERVAL
						):
							stream_handler(accumulated, len(accumulated))
							reported_chars = len(accumulated)
							last_callback_at = now

					self._merge_streamed_tool_calls(streamed_tool_calls, delta.get("tool_calls"))

				# ``time.sleep(0)`` releases the GIL and lets NVDA's main
				# thread service speech, input, and watchdog callbacks when
				# a local server has already buffered many SSE events.
				now = time.monotonic()
				if now - last_yield_at >= _STREAM_COOPERATIVE_YIELD_INTERVAL:
					time.sleep(0)
					last_yield_at = time.monotonic()
		except Exception as exc:
			log.error(
				"_stream_chat failed: model=%s base_url=%s error=%s",
				model,
				self._config.base_url,
				exc,
			)
			raise LLMProviderError(str(exc)) from exc

		if len(accumulated) > reported_chars:
			stream_handler(accumulated, len(accumulated))

		tool_calls = normalize_tool_calls([streamed_tool_calls[idx] for idx in sorted(streamed_tool_calls)])
		return accumulated, tool_calls, chunks

	@staticmethod
	def _merge_streamed_tool_calls(
		streamed: dict[int, dict[str, Any]],
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
			target = streamed.setdefault(
				index,
				{"type": "function", "function": {"name": "", "arguments": ""}},
			)
			if isinstance(item.get("id"), str):
				target["id"] = item["id"]
			if isinstance(item.get("type"), str):
				target["type"] = item["type"]

			func = item.get("function")
			if not isinstance(func, dict):
				continue
			tf = target.setdefault("function", {})
			if isinstance(func.get("name"), str):
				tf["name"] = f"{tf.get('name', '')}{func['name']}"
			if isinstance(func.get("arguments"), str):
				tf["arguments"] = f"{tf.get('arguments', '')}{func['arguments']}"

	# ==================================================================
	# Internal: message conversion
	# ==================================================================

	def _convert_message(self, message: Message) -> dict[str, Any]:
		"""Convert a canonical Message to an OpenAI-compat dict."""
		text_parts: list[str] = []
		content_parts: list[dict[str, Any]] = []
		has_image = False

		for part in message.parts:
			if part.type == "text" and part.text is not None:
				text_parts.append(part.text)
				content_parts.append({"type": "text", "text": part.text})
			elif part.type == "tool_result":
				text = json.dumps(part.tool_result) if part.tool_result is not None else part.text or ""
				text_parts.append(text)
				content_parts.append({"type": "text", "text": text})
			elif part.type == "image":
				if part.image is not None:
					img_b64 = base64.b64encode(part.image).decode("ascii")
					content_parts.append(
						{
							"type": "image_url",
							"image_url": {"url": f"data:image/png;base64,{img_b64}"},
						}
					)
					has_image = True
					text_parts.append("[IMAGE ATTACHED]")
			elif part.type == "tool_call":
				rendered = (
					f"[tool call: {part.tool_name or 'unknown'} arguments={json.dumps(part.tool_args or {})}]"
				)
				text_parts.append(rendered)
				content_parts.append({"type": "text", "text": rendered})

		if message.role == "tool":
			return {
				"role": message.role,
				"content": "\n".join(text_parts) if text_parts else "",
			}

		return {
			"role": message.role,
			"content": (content_parts if has_image else "\n".join(text_parts)),
		}

	# ==================================================================
	# Internal: utilities
	# ==================================================================

	def _resolve_model(self) -> str:
		model = self._config.model_name
		if not model or not str(model).strip():
			raise MissingModelError("Model name is required.")
		return str(model).strip()

	def _model_supports_images(self, model_id: str) -> bool:
		info = self._capabilities_for_model(model_id)
		return info.supports("image_input")

	@staticmethod
	def _has_image_parts(messages: list[Message]) -> bool:
		for msg in messages:
			for part in msg.parts:
				if part.type == "image":
					return True
		return False

	@staticmethod
	def _parse_choice(response: dict[str, Any]) -> dict[str, Any]:
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

	@staticmethod
	def _extract_tool_calls(choice: dict[str, Any]) -> list[ToolCall] | None:
		tool_calls = choice.get("tool_calls")
		if isinstance(tool_calls, list):
			return normalize_tool_calls(tool_calls)
		function_call = choice.get("function_call")
		if isinstance(function_call, dict):
			return normalize_tool_calls([{"function": function_call}])
		return None

	@staticmethod
	def _build_tool_definitions(
		tools: list[Tool] | None,
	) -> list[dict[str, Any]] | None:
		if not tools:
			return None
		return [build_function_tool_definition(t) for t in tools]
