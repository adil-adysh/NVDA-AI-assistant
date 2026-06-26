# -*- coding: utf-8 -*-
from __future__ import annotations

import threading
from collections.abc import Callable

from logHandler import log

from ..config.state import ProviderState, subscribe_provider_state_change, unsubscribe_provider_state_change
from ..core.canonical import Message, Tool
from ..core.messages import LLMResponse, SummaryResponse
from .interfaces import LLMProvider, PartialCallback, ProgressCallback, ProviderModelInfo
from ._provider_runtime import ProviderRuntime


class ProviderProxy(LLMProvider):
	def __init__(self) -> None:
		self._runtime = ProviderRuntime()
		subscribe_provider_state_change(self._on_provider_state_change)

	def _on_provider_state_change(self, _provider_state: ProviderState) -> None:
		self._runtime.refresh_configuration()

	def _warn_if_main_thread(self, method_name: str) -> None:
		if threading.current_thread() is threading.main_thread():
			log.warning("ProviderProxy.%s called on main thread; this may block NVDA UI", method_name)

	def provider_name(self) -> str:
		self._warn_if_main_thread("provider_name")
		return self._runtime.provider_name()

	def supports_streaming(self) -> bool:
		self._warn_if_main_thread("supports_streaming")
		return self._runtime.supports_streaming()

	def supports_image_description(self) -> bool:
		self._warn_if_main_thread("supports_image_description")
		return self._runtime.supports_image_description()

	def list_models(self) -> tuple[ProviderModelInfo, ...]:
		self._warn_if_main_thread("list_models")
		return self._runtime.list_models()

	def get_model_info(self, model_name: str | None = None) -> ProviderModelInfo | None:
		self._warn_if_main_thread("get_model_info")
		return self._runtime.get_model_info(model_name=model_name)

	def summarize(self, prompt: str, stream_handler: PartialCallback | None = None) -> SummaryResponse:
		self._warn_if_main_thread("summarize")
		return self._runtime.summarize(prompt, stream_handler=stream_handler)

	def describe_image(
		self,
		image_base64: str,
		prompt: str,
		stream_handler: PartialCallback | None = None,
	) -> SummaryResponse:
		self._warn_if_main_thread("describe_image")
		return self._runtime.describe_image(
			image_base64=image_base64,
			prompt=prompt,
			stream_handler=stream_handler,
		)

	def generate(
		self,
		messages: list[Message],
		tools: list[Tool] | None = None,
		stream_handler: Callable[[str, int], None] | None = None,
	) -> LLMResponse:
		self._warn_if_main_thread("generate")
		return self._runtime.generate(messages=messages, tools=tools, stream_handler=stream_handler)

	def ensure_model_available(self, on_progress: ProgressCallback | None = None) -> str | None:
		self._warn_if_main_thread("ensure_model_available")
		return self._runtime.ensure_model_available(on_progress=on_progress)

	def close(self) -> None:
		try:
			unsubscribe_provider_state_change(self._on_provider_state_change)
		except Exception:
			log.exception("Error unsubscribing provider state listener")
		self._runtime.close()
