# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
import threading
import time
from collections.abc import Callable
from typing import Any

from logHandler import log

from ..config.settings import (
	is_progress_enabled,
	is_streaming_enabled,
)
from ..observability.context import ExecutionContext
from ..observability.metrics import RequestMetrics
from ..observability.reporter import FileMetricsReporter, MetricsReporter
from ..providers.interfaces import LLMProviderError
from ..service.error_presentation import present_error
from ..ui import nvda_ui


class BaseCoordinator:
	"""Shared background task coordinator for NVDA AI assistant features."""

	MIN_CHARS: int = 80
	DELTA_THRESHOLD: int = 180
	PREVIEW_LENGTH: int = 120

	def __init__(self, metrics_reporter: MetricsReporter | None = None) -> None:
		"""Initialize shared coordinator state."""
		super().__init__()
		self._lock = threading.Lock()
		self._active_worker: threading.Thread | None = None
		self._last_announced_chars = 0
		self._request_metrics: RequestMetrics | None = None
		self.execution_context: ExecutionContext | None = None
		self.metrics_reporter = metrics_reporter or FileMetricsReporter()

	def start_task(self, *args: Any, **kwargs: Any) -> None:
		"""Public entrypoint to start a background task.

		Handles concurrency guard and worker startup.
		"""
		with self._lock:
			if self._active_worker is not None and self._active_worker.is_alive():
				self._queue_to_nvda(nvda_ui.message, self._get_busy_message())
				return

		worker = threading.Thread(
			target=self._run_in_background,
			args=args,
			kwargs=kwargs,
			name=self._get_task_name(),
			daemon=True,
		)
		self._active_worker = worker
		worker.start()

	def _run_in_background(self, *args: Any, **kwargs: Any) -> None:
		"""Internal wrapper executed in the background thread."""
		self._last_announced_chars = 0
		self.execution_context = ExecutionContext()
		self._pre_run(*args, **kwargs)

		progress_callback = self._handle_progress if is_streaming_enabled() else None
		self._request_metrics = self._build_request_metrics(*args, **kwargs)
		if self._request_metrics is not None:
			self._request_metrics.start_time = time.perf_counter()

		try:
			result = self._run_task_logic(progress_callback, *args, **kwargs)
		except LLMProviderError as error:
			log.exception("Task failed with provider error")
			self._finalize_request_metrics(False, error)
			self._handle_error(error)
		except Exception as error:
			log.exception("Task failed with unexpected exception")
			self._finalize_request_metrics(False, error)
			self._handle_error(error)
		else:
			self._finalize_request_metrics(True, None, result)
			self._queue_to_nvda(self._present_result, result)
		finally:
			with self._lock:
				self._active_worker = None

	def _handle_progress(self, partial_text: str, generated_chars: int) -> None:
		"""Shared progress handler with throttling and preview generation."""
		if generated_chars > 0:
			nvda_ui.play_streaming_tone()

		if not is_progress_enabled():
			return
		if generated_chars < self.MIN_CHARS:
			return

		delta = generated_chars - self._last_announced_chars
		if delta < self.DELTA_THRESHOLD:
			return

		self._last_announced_chars = generated_chars
		preview = " ".join(partial_text.strip().split())[-self.PREVIEW_LENGTH:]
		message_text = self._format_progress_message(generated_chars, preview)
		if message_text:
			self._queue_to_nvda(nvda_ui.message, message_text)

	def _handle_error(self, error: Exception) -> None:
		"""Handle and dispatch errors to NVDA UI."""
		message_text = self._format_error_message(error)
		self._queue_to_nvda(nvda_ui.message, message_text)

	def _queue_to_nvda(
		self,
		callback: Callable[..., None],
		*args: Any,
	) -> None:
		"""Queue execution on the NVDA event queue."""
		nvda_ui.queue(callback, *args)

	def _build_request_metrics(self, *args: Any, **kwargs: Any) -> RequestMetrics | None:
		"""Return a metrics object for the current request, if supported."""
		return None

	def _finalize_request_metrics(
		self,
		success: bool,
		error: Exception | None = None,
		result: Any | None = None,
	) -> None:
		if self._request_metrics is None:
			return
		end_time = time.perf_counter()
		self._request_metrics.finalize(end_time, success, str(error) if error is not None else None)
		try:
			self._report_request_metrics(self._request_metrics, result)
		except Exception:
			log.exception("Failed to report request metrics")
		self._request_metrics = None

	def _report_request_metrics(self, metrics: RequestMetrics, result: Any | None) -> None:
		"""Report request metrics. Subclasses may override this to capture richer telemetry."""
		log.debug("Request metrics: %s", metrics.to_dict())
		if self.metrics_reporter:
			self.metrics_reporter.report(metrics)

	# --- Required Hooks ---

	def _run_task_logic(
		self,
		progress_callback: Callable[[str, int], None] | None,
		*args: Any,

		**kwargs: Any,
	) -> Any:
		"""Subclasses must perform feature-specific background work and return a result."""
		raise NotImplementedError

	def _present_result(self, result: Any) -> None:
		"""Subclasses must present the final result through NVDA UI."""
		raise NotImplementedError

	def _format_progress_message(self, generated_chars: int, preview: str) -> str:
		"""Subclasses must format the progress message text."""
		raise NotImplementedError

	# --- Optional Hooks ---

	def _get_task_name(self) -> str:
		"""Return the background thread name or task name."""
		return "BaseCoordinatorTask"

	def _get_busy_message(self) -> str:
		"""Return the message shown when the task is already running."""
		return "Task already in progress"

	def _format_error_message(self, error: Exception) -> str:
		"""Return a formatted error message for NVDA UI."""
		return present_error(error).message

	def _pre_run(self, *args: Any, **kwargs: Any) -> None:
		"""Optional hook run in the background thread before task logic."""
		return None
