# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    model_name: str
    timeout_seconds: float
    enable_progress: bool
    num_ctx: int
    max_retries: int
    retry_backoff_seconds: float
    generate_temperature: float
    generate_top_k: int
    generate_top_p: float
    generate_max_tokens: int


@dataclass(frozen=True)
class OpenAICompatConfig(ProviderConfig):
    """Unified configuration for any OpenAI-compatible provider.

    Covers Ollama, OpenAI, Gemini OpenAI-compat, LiteRT, llama.cpp, etc.
    """

    base_url: str
    api_key: str = ""
    api_token: str | None = None
    chat_path: str = "/v1/chat/completions"
    models_path: str = "/v1/models"
    organization: str | None = None
    think: bool = False


# ---------------------------------------------------------------------------
# Backward-compatibility aliases — these will be removed after migration.
# ---------------------------------------------------------------------------

OllamaConfig = OpenAICompatConfig
GeminiConfig = OpenAICompatConfig
OpenAIConfig = OpenAICompatConfig
LiteRTConfig = OpenAICompatConfig
