# -*- coding: utf-8 -*-
from __future__ import annotations

import abc
from collections.abc import Callable
from typing import Any

from ..models import ChatMessage, LLMRequest, LLMResponse, SummaryResponse

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


def format_chat_messages(messages: list[ChatMessage] | None) -> str:
    parts: list[str] = []
    if not messages:
        return ""

    for msg in messages:
        role = msg.role.upper()
        if msg.role == "tool" and msg.tool_name:
            parts.append(f"{role}/{msg.tool_name}: {msg.content or ''}")
        elif msg.content:
            parts.append(f"{role}: {msg.content}")
        if msg.image_base64:
            parts.append(f"{role}: [IMAGE_ATTACHED]")
        if msg.tool_calls:
            parts.append(f"{role}: [TOOL_CALLS] {msg.tool_calls}")

    return "\n".join(parts)
