# -*- coding: utf-8 -*-
from __future__ import annotations

import threading
from collections.abc import Callable

from logHandler import log

from ..config.settings import get_active_provider_config
from ..core.canonical import Message, Tool
from ..core.messages import LLMResponse, SummaryResponse
from .config import ProviderConfig
from .interfaces import LLMProvider, PartialCallback, ProgressCallback, ProviderModelInfo


ProviderResolver = Callable[[], ProviderConfig]
ProviderFactoryFn = Callable[[ProviderConfig], LLMProvider]


class ProviderRuntime:
	def __init__(
		self,
		config_resolver: ProviderResolver = get_active_provider_config,
		provider_factory: ProviderFactoryFn | None = None,
	) -> None:
		self._lock = threading.RLock()
		self._config_resolver = config_resolver
		self._provider_factory = provider_factory or self._build_provider
		self._active_config: ProviderConfig = self._config_resolver()
		self._provider: LLMProvider | None = None

	def refresh_configuration(self) -> None:
		with self._lock:
			current_config = self._config_resolver()
			if current_config == self._active_config:
				return
			self._active_config = current_config
			self._close_provider_locked()

	def provider_name(self) -> str:
		return self.get_provider().provider_name()

	def supports_streaming(self) -> bool:
		return self.get_provider().supports_streaming()

	def supports_image_description(self) -> bool:
		return self.get_provider().supports_image_description()

	def list_models(self) -> tuple[ProviderModelInfo, ...]:
		return self.get_provider().list_models()

	def get_model_info(self, model_name: str | None = None) -> ProviderModelInfo | None:
		return self.get_provider().get_model_info(model_name=model_name)

	def summarize(self, prompt: str, stream_handler: PartialCallback | None = None) -> SummaryResponse:
		return self.get_provider().summarize(prompt, stream_handler=stream_handler)

	def describe_image(
		self,
		image_base64: str,
		prompt: str,
		stream_handler: PartialCallback | None = None,
	) -> SummaryResponse:
		return self.get_provider().describe_image(
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
		return self.get_provider().generate(messages=messages, tools=tools, stream_handler=stream_handler)

	def ensure_model_available(self, on_progress: ProgressCallback | None = None) -> str | None:
		return self.get_provider().ensure_model_available(on_progress=on_progress)

	def get_provider(self) -> LLMProvider:
		with self._lock:
			current_config = self._config_resolver()
			if current_config != self._active_config:
				self._active_config = current_config
				self._close_provider_locked()
			if self._provider is None:
				self._provider = self._provider_factory(self._active_config)
			return self._provider

	def close(self) -> None:
		with self._lock:
			self._close_provider_locked()

	def _close_provider_locked(self) -> None:
		provider = self._provider
		self._provider = None
		if provider is None:
			return
		try:
			provider.close()
		except Exception:
			log.exception("Error closing provider in ProviderRuntime")

	def _build_provider(self, config: ProviderConfig) -> LLMProvider:
		from .factory import ProviderFactory

		return ProviderFactory.create_provider(config)
