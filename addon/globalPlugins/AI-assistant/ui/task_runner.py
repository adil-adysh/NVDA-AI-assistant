"""Small, explicit concurrency boundary for UI-owned background work.

The UI layer is the only place that knows how to dispatch back to wx.  Service
code remains UI-free, and dialog code never updates controls from a worker.
"""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
import threading
import time
from typing import Generic, TypeVar
import uuid

import logging
import wx

from ..core.diagnostics import NullTaskDiagnostics, TaskDiagnostics
from ..core.operation_outcome import OperationOutcome, resolve_outcome
from ..service.error_reporter import ErrorContext, ErrorReporter, error_reporter

log = logging.getLogger(__name__)

T = TypeVar("T")


class UiDispatcher:
	"""Dispatch callbacks onto wx's main event loop."""

	@staticmethod
	def post(callback: Callable[[], None]) -> None:
		try:
			wx.CallAfter(callback)
		except Exception:
			# NVDA may be shutting down while a worker is completing.
			log.debug("Unable to dispatch UI callback during shutdown", exc_info=True)


@dataclass(slots=True)
class TaskHandle(Generic[T]):
	"""Cancellation and completion state for one background operation."""

	cancel_event: threading.Event
	_future: Future[T]
	_completion: Future[OperationOutcome] = field(default_factory=Future)
	_detached: threading.Event = field(default_factory=threading.Event)

	def detach(self) -> None:
		"""Stop view delivery without cancelling application work."""
		self._detached.set()

	@property
	def outcome(self) -> OperationOutcome | None:
		return self._completion.result() if self._completion.done() else None

	def cancel(self) -> None:
		self.cancel_event.set()
		self._future.cancel()

	@property
	def done(self) -> bool:
		return self._future.done()


class BackgroundTaskRunner:
	"""Run blocking application services away from the wx thread.

	``work`` receives a cancellation event and must not touch wx objects.  All
	completion callbacks are dispatched through ``UiDispatcher`` and optionally
	guarded by ``is_alive`` so callbacks cannot mutate destroyed dialogs.
	"""

	def __init__(self, max_workers: int = 4, *, diagnostics: TaskDiagnostics | None = None) -> None:
		self._diagnostics = diagnostics if diagnostics is not None else NullTaskDiagnostics()
		self._error_reporter = error_reporter
		self._executor = ThreadPoolExecutor(
			max_workers=max_workers,
			thread_name_prefix="NVDA-AI-worker",
		)

	def configure_diagnostics(self, diagnostics: TaskDiagnostics) -> None:
		"""Wire the infrastructure adapter at application composition."""
		self._diagnostics = diagnostics

	def submit(
		self,
		work: Callable[[threading.Event], T],
		*,
		on_success: Callable[[T], None] | None = None,
		on_error: Callable[[Exception], None] | None = None,
		on_finally: Callable[[], None] | None = None,
		is_alive: Callable[[], bool] | None = None,
		task_name: str | None = None,
		error_reporter_instance: ErrorReporter | None = None,
	) -> TaskHandle[T]:
		cancel_event = threading.Event()
		operation_id = uuid.uuid4().hex
		name = task_name or getattr(work, "__qualname__", "background_task")
		reporter = error_reporter_instance or self._error_reporter
		submitted_at = time.perf_counter()
		started_at: float | None = None

		diagnostics = self._diagnostics

		def report(event: str, **attributes: object) -> None:
			try:
				diagnostics.emit(event, operation_id, **attributes)
			except Exception:
				log.debug("Unable to report AI task event", exc_info=True)

		def dispatch(callback: Callable[[], None], *, deliver_after_cancel: bool = False) -> None:
			def guarded_callback() -> None:
				if handle._detached.is_set():
					return
				if cancel_event.is_set() and not deliver_after_cancel:
					return
				if is_alive is None or is_alive():
					try:
						callback()
					except Exception as error:
						reporter.report(
							error,
							ErrorContext(operation=name, origin="background task callback"),
						)

			UiDispatcher.post(guarded_callback)

		def execute() -> T:
			nonlocal started_at
			started_at = time.perf_counter()
			report(
				"task_started",
				task=name,
				queue_delay_ms=round((started_at - submitted_at) * 1000, 3),
			)
			return work(cancel_event)

		future = self._executor.submit(execute)

		handle = TaskHandle(cancel_event, future)

		def completed(completed_future: Future[T]) -> None:
			error = None
			result = None
			if not completed_future.cancelled():
				try:
					result = completed_future.result()
				except Exception as failure:
					error = failure
			outcome = resolve_outcome(
				cancelled=completed_future.cancelled() or cancel_event.is_set(), error=error,
			)
			handle._completion.set_result(outcome)
			attributes = {
				"task": name,
				"duration_ms": round((time.perf_counter() - (started_at or submitted_at)) * 1000, 3),
			}
			if outcome is OperationOutcome.FAILED:
				attributes["error_type"] = type(error).__name__
			report({
				OperationOutcome.SUCCEEDED: "task_completed",
				OperationOutcome.FAILED: "task_failed",
				OperationOutcome.CANCELLED: "task_cancelled",
			}[outcome], **attributes)
			if outcome is OperationOutcome.FAILED:
				log.error("Background UI task failed: %s", error, exc_info=(type(error), error, error.__traceback__))
				context = ErrorContext(operation=name, origin="background task")
				if on_error is not None:
					dispatch(lambda error=error: on_error(error))
				else:
					dispatch(lambda error=error: reporter.report(error, context))
			elif outcome is OperationOutcome.SUCCEEDED and on_success is not None:
				dispatch(lambda: on_success(result))
			if on_finally is not None:
				dispatch(on_finally, deliver_after_cancel=True)

		future.add_done_callback(completed)
		return handle


background_tasks = BackgroundTaskRunner()


__all__ = ["BackgroundTaskRunner", "TaskHandle", "UiDispatcher", "background_tasks"]
