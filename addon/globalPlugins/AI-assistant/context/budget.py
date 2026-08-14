# -*- coding: utf-8 -*-
"""Provider-neutral prompt and context-window budgeting primitives."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol


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


def validate_prompt_budget(prompt: str, budget: ContextWindowBudget, counter: TokenCounter) -> int:
	prompt_tokens = counter.count(prompt)
	if prompt_tokens > budget.input_token_limit:
		raise ContextBudgetError(
			"Prompt exceeds the available input budget: "
			f"{prompt_tokens} > {budget.input_token_limit} tokens"
		)
	return prompt_tokens
