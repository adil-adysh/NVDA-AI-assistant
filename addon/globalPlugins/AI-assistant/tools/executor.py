# -*- coding: utf-8 -*-
"""Structured, bounded and policy-controlled tool execution.

The conversation stack stays synchronous.  ``ToolExecutor`` is the single
coordination point for validation, authorization, timeouts, cancellation,
budgets, result normalization and diagnostics.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from typing import Any

from ..core.cancellation import (
	CancellationToken,
	RequestCancelled,
	current_cancellation_token,
)
from ..core.tooling import (
	MAX_TOOL_RESULT_CHARS,
	ToolCall,
	ToolContentBlock,
	ToolErrorCategory,
	ToolErrorSource,
	ToolExecutionResult,
)
from .budget import ToolExecutionBudget, ToolExecutionTracker
from .errors import (
	ToolArgumentError,
	ToolBudgetExceeded,
	ToolCancelledError,
	ToolError,
	ToolExecutionError,
	ToolPermissionDenied,
	ToolTimeoutError,
	UnknownToolError,
	bounded_message,
)
from .policy import DefaultToolPermissionPolicy, ToolPermissionPolicy
from .provider import ToolCallContext
from .registry import ToolBinding, ToolCatalogSnapshot, ToolRegistry
from .schema import format_violations, validate_arguments

log = logging.getLogger(__name__)

_SECRET_PATTERNS = (
	re.compile(r"(?i)(authorization\s*:\s*)(\S.*)"),
	re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
	re.compile(r"(?i)((?:api[_-]?key|token|secret|password)\s*[=:]\s*)\S+"),
)


class ToolExecutor:
	def __init__(
		self,
		tool_registry: ToolRegistry,
		*,
		policy: ToolPermissionPolicy | None = None,
		budget: ToolExecutionBudget | None = None,
	) -> None:
		self._tool_registry = tool_registry
		self._policy = policy or DefaultToolPermissionPolicy()
		self._budget = budget or ToolExecutionBudget()
		self._diagnostics_lock = threading.Lock()
		self._diagnostics: dict[str, Any] = {
			"calls": 0,
			"successes": 0,
			"failures": 0,
			"by_category": {},
			"last_error": None,
		}

	def new_tracker(self) -> ToolExecutionTracker:
		return ToolExecutionTracker(self._budget)

	def diagnostics(self) -> dict[str, Any]:
		with self._diagnostics_lock:
			return {
				"calls": self._diagnostics["calls"],
				"successes": self._diagnostics["successes"],
				"failures": self._diagnostics["failures"],
				"by_category": dict(self._diagnostics["by_category"]),
				"last_error": self._diagnostics["last_error"],
			}

	def execute(
		self,
		tool_call: ToolCall,
		*,
		snapshot: ToolCatalogSnapshot | None = None,
		tracker: ToolExecutionTracker | None = None,
		cancellation_token: CancellationToken | None = None,
	) -> ToolExecutionResult:
		started = time.monotonic()
		effective_snapshot = snapshot or self._tool_registry.snapshot()
		binding = effective_snapshot.resolve(tool_call.name)
		if binding is None:
			return self._finish(
				self._error_result(tool_call, UnknownToolError(tool_call.name), started)
			)

		if tool_call.parse_error:
			return self._finish(
				self._error_result(
					tool_call,
					ToolArgumentError(tool_call.parse_error),
					started,
					binding=binding,
				)
			)

		arguments = tool_call.arguments
		if not isinstance(arguments, dict):
			return self._finish(
				self._error_result(
					tool_call,
					ToolArgumentError("arguments must be a JSON object"),
					started,
					binding=binding,
				)
			)
		violations = validate_arguments(binding.definition.input_schema, arguments)
		if violations:
			return self._finish(
				self._error_result(
					tool_call,
					ToolArgumentError(format_violations(violations), violations=violations),
					started,
					binding=binding,
				)
			)

		try:
			self._policy.authorize(binding, arguments)
		except ToolPermissionDenied as error:
			return self._finish(self._error_result(tool_call, error, started, binding=binding))

		effective_tracker = tracker or self.new_tracker()
		try:
			effective_tracker.reserve_call()
		except ToolBudgetExceeded as error:
			return self._finish(self._error_result(tool_call, error, started, binding=binding))

		is_cancelled = self._cancellation_probe(cancellation_token)
		if is_cancelled():
			return self._finish(
				self._error_result(tool_call, ToolCancelledError("Tool call cancelled"), started, binding=binding)
			)

		timeout = effective_tracker.call_timeout()
		context = ToolCallContext(
			tool_id=binding.tool_id,
			tool_name=binding.model_name,
			tool_call_id=tool_call.id,
			provider_id=binding.provider_id,
			timeout_seconds=timeout,
			cancellation_requested=is_cancelled,
		)

		try:
			state, value, error = self._invoke_bounded(binding, arguments, context, timeout, is_cancelled)
		except BaseException as unexpected:  # never let an executor bug escape as success
			state, value, error = "error", None, unexpected

		if state == "timeout":
			return self._finish(
				self._error_result(
					tool_call,
					ToolTimeoutError(
						f"Tool '{binding.model_name}' timed out after {timeout:.1f}s"
					),
					started,
					binding=binding,
				)
			)
		if state == "cancelled":
			return self._finish(
				self._error_result(
					tool_call,
					ToolCancelledError(f"Tool '{binding.model_name}' was cancelled"),
					started,
					binding=binding,
				)
			)
		if state == "error":
			return self._finish(self._error_result(tool_call, error, started, binding=binding))

		return self._finish(
			self._success_result(tool_call, value, binding, started, effective_tracker.budget.max_result_chars)
		)

	def execute_tool_calls(
		self,
		tool_calls: list[ToolCall],
		*,
		snapshot: ToolCatalogSnapshot | None = None,
		tracker: ToolExecutionTracker | None = None,
		cancellation_token: CancellationToken | None = None,
	) -> list[ToolExecutionResult]:
		"""Execute calls serially (default) and return one result per call.

		Every model-requested call receives a result so provider history stays
		valid even when a budget has already been exhausted.
		"""
		effective_snapshot = snapshot or self._tool_registry.snapshot()
		effective_tracker = tracker or self.new_tracker()
		results: list[ToolExecutionResult] = []
		for tool_call in tool_calls:
			results.append(
				self.execute(
					tool_call,
					snapshot=effective_snapshot,
					tracker=effective_tracker,
					cancellation_token=cancellation_token,
				)
			)
		return results

	# ------------------------------------------------------------------
	# Internals
	# ------------------------------------------------------------------

	@staticmethod
	def _cancellation_probe(token: CancellationToken | None) -> Callable[[], bool]:
		def probe() -> bool:
			if token is not None and token.cancelled:
				return True
			current = current_cancellation_token()
			return current is not None and current.cancelled

		return probe

	def _invoke_bounded(
		self,
		binding: ToolBinding,
		arguments: dict[str, Any],
		context: ToolCallContext,
		timeout: float,
		is_cancelled: Callable[[], bool],
	) -> tuple[str, object, BaseException | None]:
		"""Run the backend on a daemon thread and join it with a deadline.

		A timed-out or cancelled call is reported as unconfirmed: the thread
		cannot be force-killed, so automatic retries of side-effecting tools
		would be unsafe.
		"""
		state: dict[str, object] = {}
		done = threading.Event()

		def worker() -> None:
			try:
				state["value"] = binding.invoke(arguments, context)
			except BaseException as error:  # noqa: BLE001 - classified by the caller
				state["error"] = error
			finally:
				done.set()

		thread = threading.Thread(
			target=worker,
			name=f"AIToolExec-{binding.model_name}",
			daemon=True,
		)
		thread.start()
		deadline = time.monotonic() + timeout
		while not done.wait(0.02):
			if is_cancelled():
				return "cancelled", None, None
			if time.monotonic() >= deadline:
				return "timeout", None, None
		if is_cancelled():
			return "cancelled", None, None
		error = state.get("error")
		if error is not None:
			return "error", None, error
		return "ok", state.get("value"), None

	def _success_result(
		self,
		tool_call: ToolCall,
		value: object,
		binding: ToolBinding,
		started: float,
		max_result_chars: int,
	) -> ToolExecutionResult:
		duration_ms = (time.monotonic() - started) * 1000.0
		if isinstance(value, ToolExecutionResult):
			return _adopt_provider_result(value, tool_call, binding, duration_ms, max_result_chars)
		if isinstance(value, ToolContentBlock):
			blocks = (value,)
			structured = None
		elif isinstance(value, str):
			blocks = (ToolContentBlock.text_block(value),)
			structured = None
		elif value is None:
			blocks = ()
			structured = None
		elif isinstance(value, (dict, list, int, float, bool)):
			blocks = (ToolContentBlock.json_block(value),)
			structured = value
		else:
			raise ToolExecutionError(
				f"Tool '{binding.model_name}' returned an unsupported value type "
				f"{type(value).__name__}"
			)
		return ToolExecutionResult(
			tool_name=binding.model_name,
			tool_call_id=tool_call.id,
			tool_id=binding.tool_id,
			provider_id=binding.provider_id,
			ok=True,
			content=blocks,
			structured_content=structured,
			duration_ms=duration_ms,
			metadata={"generation": binding.generation},
		).bounded(max_result_chars)

	def _error_result(
		self,
		tool_call: ToolCall,
		error: BaseException,
		started: float,
		*,
		binding: ToolBinding | None = None,
	) -> ToolExecutionResult:
		duration_ms = (time.monotonic() - started) * 1000.0
		category, message, source, uncertain, confirmed = _classify(error, tool_call.name)
		metadata: dict[str, Any] = {}
		if binding is not None:
			metadata["generation"] = binding.generation
		return ToolExecutionResult(
			tool_name=binding.model_name if binding is not None else tool_call.name,
			tool_call_id=tool_call.id,
			tool_id=binding.tool_id if binding is not None else None,
			provider_id=binding.provider_id if binding is not None else None,
			ok=False,
			error_category=category,
			error_message=_safe_message(message),
			error_source=source,
			duration_ms=duration_ms,
			cancelled=category == "cancelled",
			timed_out=category == "timeout",
			uncertain=uncertain,
			termination_confirmed=confirmed,
			metadata=metadata,
		)

	def _finish(self, result: ToolExecutionResult) -> ToolExecutionResult:
		bounded = result.bounded(MAX_TOOL_RESULT_CHARS)
		with self._diagnostics_lock:
			self._diagnostics["calls"] += 1
			if bounded.ok:
				self._diagnostics["successes"] += 1
			else:
				self._diagnostics["failures"] += 1
				category = bounded.error_category or "execution_error"
				counts = self._diagnostics["by_category"]
				counts[category] = counts.get(category, 0) + 1
				self._diagnostics["last_error"] = bounded.error_message
		if not bounded.ok:
			log.debug(
				"Tool %s failed (%s): %s",
				bounded.tool_name,
				bounded.error_category,
				bounded.error_message,
			)
		return bounded


def _adopt_provider_result(
	result: ToolExecutionResult,
	tool_call: ToolCall,
	binding: ToolBinding,
	duration_ms: float,
	max_result_chars: int,
) -> ToolExecutionResult:
	metadata = dict(result.metadata)
	metadata["generation"] = binding.generation
	ok = result.ok
	error_category = result.error_category
	error_source = result.error_source
	error_message = result.error_message
	if not ok:
		# A tool-level error result (the future MCP ``isError=true`` case) must
		# still carry a classified host-side category for the conversation.
		error_category = error_category or "execution_error"
		error_source = error_source or "tool"
		error_message = error_message or f"Tool '{binding.model_name}' reported an error"
	if error_message is not None:
		error_message = _safe_message(error_message)
	return ToolExecutionResult(
		tool_name=binding.model_name,
		tool_call_id=tool_call.id or result.tool_call_id,
		tool_id=binding.tool_id,
		provider_id=binding.provider_id,
		ok=ok,
		content=result.content,
		structured_content=result.structured_content,
		error_category=error_category,
		error_message=error_message,
		error_source=error_source,
		duration_ms=duration_ms,
		cancelled=result.cancelled,
		timed_out=result.timed_out,
		termination_confirmed=result.termination_confirmed,
		uncertain=result.uncertain,
		metadata=metadata,
	).bounded(max_result_chars)


def _classify(
	error: BaseException | None,
	tool_name: str,
) -> tuple[ToolErrorCategory, str, ToolErrorSource, bool, bool]:
	if isinstance(error, ToolError):
		source = error.error_source
		return (
			error.category,
			error.safe_message,
			source,
			bool(getattr(error, "uncertain", False)),
			bool(getattr(error, "termination_confirmed", True)),
		)
	if isinstance(error, RequestCancelled):
		return "cancelled", f"Tool '{tool_name}' was cancelled", "host", False, False
	if error is None:
		return "execution_error", f"Tool '{tool_name}' failed without an error", "tool", False, True
	return (
		"execution_error",
		f"Tool '{tool_name}' execution failed: {error}",
		"tool",
		False,
		True,
	)


def _safe_message(message: str) -> str:
	text = bounded_message(message)
	for pattern in _SECRET_PATTERNS:
		text = pattern.sub(lambda match: match.group(1) + "[redacted]", text)
	return text
