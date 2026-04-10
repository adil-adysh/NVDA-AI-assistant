# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    model_name: str
    timeout_seconds: float
    enable_streaming: bool
    enable_progress: bool
    num_ctx: int
    max_retries: int
    retry_backoff_seconds: float
    generate_temperature: float
    generate_top_k: int
    generate_top_p: float


@dataclass(frozen=True)
class OllamaConfig(ProviderConfig):
    server_url: str
    keep_alive: str
    generate_presence_penalty: float


@dataclass(frozen=True)
class GeminiConfig(ProviderConfig):
    api_key: str
    api_token: str | None
    base_url: str
