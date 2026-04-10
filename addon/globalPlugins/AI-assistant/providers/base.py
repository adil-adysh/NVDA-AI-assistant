# -*- coding: utf-8 -*-
from __future__ import annotations

import abc
from collections.abc import Callable
from typing import Any

from ..models import LLMRequest, LLMResponse, SummaryResponse

PartialCallback = Callable[[str, int], None]
ProgressCallback = Callable[[str], None]


class LLMProviderError(RuntimeError):
    """Base exception for LLM provider failures."""


class LLMProvider(abc.ABC):
    """Abstract interface for cloud/local LLM providers."""

    @abc.abstractmethod
    def provider_name(self) -> str:
        raise NotImplementedError

    @abc.abstractmethod
    def supports_streaming(self) -> bool:
        raise NotImplementedError

    @abc.abstractmethod
    def supports_image_description(self) -> bool:
        raise NotImplementedError

    @abc.abstractmethod
    def summarize(self, prompt: str, stream_handler: PartialCallback | None = None) -> SummaryResponse:
        raise NotImplementedError

    @abc.abstractmethod
    def describe_image(
        self,
        image_base64: str,
        prompt: str,
        stream_handler: PartialCallback | None = None,
    ) -> SummaryResponse:
        raise NotImplementedError

    @abc.abstractmethod
    def generate(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError

    @abc.abstractmethod
    def ensure_model_available(self, on_progress: ProgressCallback | None = None) -> str | None:
        raise NotImplementedError

    def close(self) -> None:
        """Optional cleanup hook for provider implementations."""
        return None
