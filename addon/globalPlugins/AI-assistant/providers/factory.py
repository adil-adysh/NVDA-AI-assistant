# -*- coding: utf-8 -*-
from __future__ import annotations

from ..settings import (
    get_provider,
    get_ollama_model_name,
    get_ollama_server_url,
    get_gemini_api_key,
    get_gemini_api_token,
    get_gemini_base_url,
    get_gemini_model_name,
    get_timeout_seconds,
)
from .gemini_provider import GeminiProvider
from .ollama_provider import OllamaProvider


class ProviderFactory:
    @staticmethod
    def create_provider() -> "Provider":
        provider = get_provider().strip().lower()
        timeout_seconds = get_timeout_seconds()

        if provider == "gemini":
            return GeminiProvider(
                model=get_gemini_model_name(),
                api_key=get_gemini_api_key(),
                api_token=get_gemini_api_token(),
                base_url=get_gemini_base_url(),
                timeout_seconds=timeout_seconds,
            )

        if provider == "ollama":
            return OllamaProvider(
                model=get_ollama_model_name(),
                server_url=get_ollama_server_url(),
                timeout_seconds=timeout_seconds,
            )

        raise ValueError(f"Unsupported provider: {provider}")


Provider = OllamaProvider | GeminiProvider
