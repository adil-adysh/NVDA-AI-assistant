# -*- coding: utf-8 -*-
from __future__ import annotations

from ..config.settings import get_active_provider_config
from .adapters.gemini import GeminiProvider
from .adapters.ollama import OllamaProvider
from .config import GeminiConfig, OllamaConfig, ProviderConfig
from .interfaces import LLMProvider, LLMProviderError


class ProviderFactory:
    @staticmethod
    def create_provider(config: ProviderConfig | None = None) -> LLMProvider:
        provider_config = config if config is not None else get_active_provider_config()
        try:
            if isinstance(provider_config, GeminiConfig):
                return GeminiProvider(provider_config)

            if isinstance(provider_config, OllamaConfig):
                return OllamaProvider(provider_config)

            raise ValueError(f"Unsupported provider config: {provider_config}")
        except LLMProviderError:
            raise
        except Exception as error:
            raise LLMProviderError(str(error)) from error


Provider = LLMProvider
