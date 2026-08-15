# -*- coding: utf-8 -*-
"""Provider-neutral prompt and context-window budgeting primitives."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol


LOCAL_PROVIDER_IDS = frozenset({"ollama", "litert-lm", "llama-cpp-server"})
DEFAULT_CLOUD_CONTEXT_TOKENS = 262_144
DEFAULT_CONTEXT_TOKENS = 8_192


class TokenCounter(Protocol):
	def count(self, text: str) -> int:
		...


class ApproximateTokenCounter:
	"""Conservative fallback when a provider tokenizer is unavailable."""

	def count(self, text: str) -> int:
		return max(0, math.ceil(len(text.strip()) / 4))


@dataclass(frozen=True, slots=True)
class ContextWindowBudget:
	context_window_tokens: int
	reserved_output_tokens: int
	safety_margin_tokens: int = 256
	reserved_input_tokens: int = 0

	def __post_init__(self) -> None:
		if self.context_window_tokens <= 0:
			raise ValueError("context_window_tokens must be positive")
		if self.reserved_output_tokens < 0:
			raise ValueError("reserved_output_tokens cannot be negative")
		if self.safety_margin_tokens < 0:
			raise ValueError("safety_margin_tokens cannot be negative")
		if self.reserved_input_tokens < 0:
			raise ValueError("reserved_input_tokens cannot be negative")

	@property
	def input_token_limit(self) -> int:
		return max(
			0,
			self.context_window_tokens
			- self.reserved_output_tokens
			- self.safety_margin_tokens
			- self.reserved_input_tokens,
		)


class ContextBudgetError(RuntimeError):
	"""Raised when a rendered prompt cannot fit the model context window."""


def resolve_context_window_tokens(
	*,
	provider_id: str,
	model_context_tokens: int | None,
	model_configured_tokens: int | None,
	global_configured_tokens: int | None,
	cloud_default_tokens: int = DEFAULT_CLOUD_CONTEXT_TOKENS,
	fallback_tokens: int = DEFAULT_CONTEXT_TOKENS,
) -> int:
	"""Resolve the effective context size for one active model.

	Provider metadata describes the model's hard capacity. Local runtime
	configuration may select a smaller window; cloud providers use the policy
	default when reliable metadata is unavailable.
	"""
	provider = (provider_id or "").strip().lower()
	is_local = provider in LOCAL_PROVIDER_IDS
	model_context = _positive_int(model_context_tokens)
	if model_context is not None:
		if is_local:
			configured = _positive_int(model_configured_tokens)
			return min(model_context, configured) if configured is not None else model_context
		return model_context
	if is_local:
		return (
			_positive_int(model_configured_tokens)
			or _positive_int(global_configured_tokens)
			or max(1, fallback_tokens)
		)
	return max(1, cloud_default_tokens)


def _positive_int(value: int | None) -> int | None:
	return value if isinstance(value, int) and value > 0 else None


def validate_prompt_budget(prompt: str, budget: ContextWindowBudget, counter: TokenCounter) -> int:
	prompt_tokens = counter.count(prompt)
	if prompt_tokens > budget.input_token_limit:
		raise ContextBudgetError(
			"Prompt exceeds the available input budget: "
			f"{prompt_tokens} > {budget.input_token_limit} tokens"
		)
	return prompt_tokens
