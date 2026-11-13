# -*- coding: utf-8 -*-
"""Bounded execution budgets for one chat turn."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from ..core.tooling import MAX_TOOL_RESULT_CHARS
from .errors import ToolBudgetExceeded


@dataclass(frozen=True, slots=True)
class ToolExecutionBudget:
	"""Independent caps for model/tool iteration and tool execution."""

	max_iterations: int = 5
	max_tool_calls: int = 20
	max_parallel_calls: int = 1
	call_timeout_seconds: float = 30.0
	turn_timeout_seconds: float = 300.0
	max_result_chars: int = MAX_TOOL_RESULT_CHARS

	def __post_init__(self) -> None:
		if self.max_iterations < 1:
			raise ValueError("max_iterations must be at least 1")
		if self.max_tool_calls < 1:
			raise ValueError("max_tool_calls must be at least 1")
		if self.max_parallel_calls < 1:
			raise ValueError("max_parallel_calls must be at least 1")
		if self.call_timeout_seconds <= 0 or self.turn_timeout_seconds <= 0:
			raise ValueError("tool timeouts must be positive")
		if self.max_result_chars < 1:
			raise ValueError("max_result_chars must be positive")


class ToolExecutionTracker:
	"""Mutable per-turn counters enforcing a :class:`ToolExecutionBudget`."""

	def __init__(self, budget: ToolExecutionBudget | None = None, *, clock=time.monotonic) -> None:
		self.budget = budget or ToolExecutionBudget()
		self._clock = clock
		self._started_at = clock()
		self._calls_started = 0
		self._iterations = 0
		self._lock = threading.Lock()

	def elapsed_seconds(self) -> float:
		return max(0.0, self._clock() - self._started_at)

	def remaining_seconds(self) -> float:
		return max(0.0, self.budget.turn_timeout_seconds - self.elapsed_seconds())

	def calls_started(self) -> int:
		with self._lock:
			return self._calls_started

	def begin_iteration(self) -> None:
		with self._lock:
			if self._iterations >= self.budget.max_iterations:
				raise ToolBudgetExceeded(
					f"Tool loop iteration limit reached ({self.budget.max_iterations})",
					safe_message="Tool iteration limit reached.",
				)
			self._iterations += 1
			self._check_turn_locked()

	def reserve_call(self) -> None:
		with self._lock:
			self._check_turn_locked()
			if self._calls_started >= self.budget.max_tool_calls:
				raise ToolBudgetExceeded(
					f"Tool call budget exhausted ({self.budget.max_tool_calls})",
					safe_message="Tool call budget exhausted.",
				)
			self._calls_started += 1

	def call_timeout(self) -> float:
		return max(0.001, min(self.budget.call_timeout_seconds, self.remaining_seconds()))

	def _check_turn_locked(self) -> None:
		if self.remaining_seconds() <= 0:
			raise ToolBudgetExceeded(
				"Turn time budget exhausted",
				safe_message="The tool time budget for this response was exhausted.",
			)
