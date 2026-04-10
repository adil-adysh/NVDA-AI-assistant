# -*- coding: utf-8 -*-
from __future__ import annotations

from ..settings import get_active_provider_config
from .config import GeminiConfig, OllamaConfig, ProviderConfig
from .gemini_provider import GeminiProvider
from .ollama_provider import OllamaProvider


class ProviderFactory:
    @staticmethod
    def create_provider(config: ProviderConfig | None = None) -> "Provider":
        provider_config = config if config is not None else get_active_provider_config()

        if isinstance(provider_config, GeminiConfig):
            return GeminiProvider(provider_config)

        if isinstance(provider_config, OllamaConfig):
            return OllamaProvider(provider_config)

        raise ValueError(f"Unsupported provider config: {provider_config}")


Provider = OllamaProvider | GeminiProvider
