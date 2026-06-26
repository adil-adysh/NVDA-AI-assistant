# -*- coding: utf-8 -*-
from __future__ import annotations


from ..config.settings import get_active_provider_config
from .adapters.gemini import GeminiProvider
from .adapters.litert import LiteRTLMProvider
from .adapters.ollama import OllamaProvider
from .config import GeminiConfig, LiteRTConfig, OllamaConfig, OpenAIConfig, ProviderConfig
from .interfaces import LLMProvider, LLMProviderError


class ProviderFactory:
	_provider_registry: dict[type[ProviderConfig], type[LLMProvider]] = {}

	@classmethod
	def register_provider(cls, config_type: type[ProviderConfig], provider_type: type[LLMProvider]) -> None:
		cls._provider_registry[config_type] = provider_type

	@classmethod
	def create_provider(cls, config: ProviderConfig | None = None) -> LLMProvider:
		provider_config = config if config is not None else get_active_provider_config()
		provider_type = cls._provider_registry.get(type(provider_config))
		if provider_type is None:
			raise ValueError(f"Unsupported provider config type: {type(provider_config).__name__}")
		try:
			return provider_type(provider_config)
		except LLMProviderError:
			raise
		except Exception as error:
			raise LLMProviderError(str(error)) from error


ProviderFactory.register_provider(GeminiConfig, GeminiProvider)
ProviderFactory.register_provider(OllamaConfig, OllamaProvider)
from .adapters.openai import OpenAIProvider  # noqa: E402 — cyclic import
ProviderFactory.register_provider(OpenAIConfig, OpenAIProvider)
ProviderFactory.register_provider(LiteRTConfig, LiteRTLMProvider)


Provider = LLMProvider
