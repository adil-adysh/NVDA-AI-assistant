# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..core.canonical import Message, Tool
from ..core.messages import LLMResponse, SummaryResponse
from ..settings import get_active_provider_config
from .config import ProviderConfig
from .interfaces import LLMProvider, PartialCallback, ProgressCallback
from .factory import ProviderFactory


class ProviderSession:
	def __init__(self, provider: LLMProvider, config: ProviderConfig) -> None:
		self._provider = provider
		self._active_config = config

	@classmethod
	def from_active_config(cls) -> ProviderSession:
		config = get_active_provider_config()
		provider = ProviderFactory.create_provider(config)
		return cls(provider=provider, config=config)

	def refresh(self) -> None:
		current_config = get_active_provider_config()
		if current_config == self._active_config:
			return
		self.close()
		self._active_config = current_config
		self._provider = ProviderFactory.create_provider(current_config)

	def provider_name(self) -> str:
		return self._provider.provider_name()

	def supports_streaming(self) -> bool:
		return self._provider.supports_streaming()

	def supports_image_description(self) -> bool:
		return self._provider.supports_image_description()

	def summarize(self, prompt: str, stream_handler: PartialCallback | None = None) -> SummaryResponse:
		return self._provider.summarize(prompt, stream_handler=stream_handler)

	def describe_image(
		self,
		image_base64: str,
		prompt: str,
		stream_handler: PartialCallback | None = None,
	) -> SummaryResponse:
		return self._provider.describe_image(image_base64=image_base64, prompt=prompt, stream_handler=stream_handler)

	def generate(
		self,
		messages: list[Message],
		tools: list[Tool] | None = None,
		stream_handler: Callable[[str, int], None] | None = None,
	) -> LLMResponse:
		return self._provider.generate(messages=messages, tools=tools, stream_handler=stream_handler)

	def ensure_model_available(self, on_progress: ProgressCallback | None = None) -> str | None:
		return self._provider.ensure_model_available(on_progress=on_progress)

	def close(self) -> None:
		self._provider.close()
