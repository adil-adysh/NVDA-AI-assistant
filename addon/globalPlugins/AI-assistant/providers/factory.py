# -*- coding: utf-8 -*-
from __future__ import annotations


from ..config.settings import get_active_provider_config
from .adapters.openai_compat import OpenAICompatProvider
from .config import OpenAICompatConfig, ProviderConfig
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
			# Fallback: walk MRO for registered base types (handles alias classes).
			for base in type(provider_config).__mro__:
				provider_type = cls._provider_registry.get(base)
				if provider_type is not None:
					break
		if provider_type is None:
			raise ValueError(f"Unsupported provider config type: {type(provider_config).__name__}")
		try:
			if getattr(provider_config, "provider", "") == "llama-cpp-server":
				from .adapters.llama_cpp import LlamaCppServerProvider

				return LlamaCppServerProvider(provider_config)  # type: ignore[arg-type]
			return provider_type(provider_config)
		except LLMProviderError:
			raise
		except Exception as error:
			raise LLMProviderError(str(error)) from error


ProviderFactory.register_provider(OpenAICompatConfig, OpenAICompatProvider)


Provider = LLMProvider
