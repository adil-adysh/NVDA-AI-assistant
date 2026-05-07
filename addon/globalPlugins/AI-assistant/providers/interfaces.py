# -*- coding: utf-8 -*-
from __future__ import annotations

import abc
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..core.canonical import Message, Tool
from ..core.messages import ChatMessage, LLMResponse, SummaryResponse

PartialCallback = Callable[[str, int], None]
ProgressCallback = Callable[[str], None]


class LLMProviderError(RuntimeError):
	"""Base exception for LLM provider failures."""


class ProviderConfigurationError(LLMProviderError):
	"""Raised when a provider configuration is incomplete or invalid."""


class MissingCredentialsError(ProviderConfigurationError):
	"""Raised when provider credentials are missing."""


class MissingModelError(ProviderConfigurationError):
	"""Raised when no model has been configured for a provider."""


class MissingEndpointError(ProviderConfigurationError):
	"""Raised when a provider endpoint configuration is missing."""


class MissingChatPathError(ProviderConfigurationError):
	"""Raised when a required chat endpoint path is missing."""


class UnsupportedModelError(ProviderConfigurationError):
	"""Raised when the selected model is not supported for the current workflow."""


@dataclass(frozen=True)
class SamplingDefaults:
	temperature: float | None = None
	top_p: float | None = None
	top_k: int | None = None
	max_tokens: int | None = None
	extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderModelInfo:
	id: str
	provider: str
	display_name: str | None = None
	description: str | None = None
	owned_by: str | None = None
	created: int | None = None
	context_window: int | None = None
	output_token_limit: int | None = None
	capabilities: tuple[str, ...] = ()
	sampling_defaults: SamplingDefaults = field(default_factory=SamplingDefaults)
	raw: dict[str, Any] = field(default_factory=dict)

	def supports(self, capability: str) -> bool:
		return capability in self.capabilities


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
	def list_models(self) -> tuple[ProviderModelInfo, ...]:
		raise NotImplementedError

	@abc.abstractmethod
	def get_model_info(self, model_name: str | None = None) -> ProviderModelInfo | None:
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
	def generate(
		self,
		messages: list[Message],
		tools: list[Tool] | None = None,
		stream_handler: Callable[[str, int], None] | None = None,
	) -> LLMResponse:
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
