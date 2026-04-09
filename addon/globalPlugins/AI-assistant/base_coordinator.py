# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
import logging
import threading
from collections.abc import Callable
from typing import Any

import queueHandler
import ui

from .ollama_client import OllamaClientError

logger = logging.getLogger(__name__)


class BaseCoordinator:
	"""Shared background task coordinator for NVDA AI assistant features."""

	MIN_CHARS: int = 80
	DELTA_THRESHOLD: int = 180
	PREVIEW_LENGTH: int = 120

	def __init__(self) -> None:
		"""Initialize shared coordinator state."""
		self._lock = threading.Lock()
		self._active_worker: threading.Thread | None = None
		self._last_announced_chars = 0

	def start_task(self, *args: Any, **kwargs: Any) -> None:
		"""Public entrypoint to start a background task.

		Handles concurrency guard and worker startup.
		"""
		with self._lock:
			if self._active_worker is not None and self._active_worker.is_alive():
				self._queue_to_nvda(ui.message, self._get_busy_message())
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
		self._pre_run(*args, **kwargs)

		try:
			result = self._run_task_logic(self._handle_progress, *args, **kwargs)
		except OllamaClientError as error:
			logger.exception("Task failed with OllamaClientError")
			self._handle_error(error)
		except Exception as error:
			logger.exception("Task failed with unexpected exception")
			self._handle_error(error)
		else:
			self._queue_to_nvda(self._present_result, result)
		finally:
			with self._lock:
				self._active_worker = None

	def _handle_progress(self, partial_text: str, generated_chars: int) -> None:
		"""Shared progress handler with throttling and preview generation."""
		if generated_chars < self.MIN_CHARS:
			return

		delta = generated_chars - self._last_announced_chars
		if delta < self.DELTA_THRESHOLD:
			return

		self._last_announced_chars = generated_chars
		preview = " ".join(partial_text.strip().split())[-self.PREVIEW_LENGTH:]
		message = self._format_progress_message(generated_chars, preview)
		if message:
			self._queue_to_nvda(ui.message, message)

	def _handle_error(self, error: Exception) -> None:
		"""Handle and dispatch errors to NVDA UI."""
		message = self._format_error_message(error)
		self._queue_to_nvda(ui.message, message)

	def _queue_to_nvda(
		self,
		callback: Callable[..., None],
		*args: Any,
	) -> None:
		"""Queue execution on the NVDA event queue."""
		queueHandler.queueFunction(queueHandler.eventQueue, callback, *args)

	# --- Required Hooks ---

	def _run_task_logic(
		self,
		progress_callback: Callable[[str, int], None],
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
		return str(error)

	def _pre_run(self, *args: Any, **kwargs: Any) -> None:
		"""Optional hook run in the background thread before task logic."""
		return None
