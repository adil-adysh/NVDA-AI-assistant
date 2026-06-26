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
class OllamaConfig(ProviderConfig):
    server_url: str
    keep_alive: str
    generate_presence_penalty: float
    think: bool


@dataclass(frozen=True)
class GeminiConfig(ProviderConfig):
    api_key: str
    api_token: str | None
    base_url: str


@dataclass(frozen=True)
class OpenAIConfig(ProviderConfig):
    api_key: str
    base_url: str
    chat_path: str
    organization: str | None


@dataclass(frozen=True)
class LiteRTConfig(ProviderConfig):
    """Configuration for the on-device LiteRT-LM runtime.

    Uses RuntimeManager to download the native runtime on first use.
    The model_name field holds the path to a .litertlm model file.
    """

    backend: str = "cpu"
    think: bool = False
