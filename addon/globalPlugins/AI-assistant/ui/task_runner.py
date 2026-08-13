"""Small, explicit concurrency boundary for UI-owned background work.

The UI layer is the only place that knows how to dispatch back to wx.  Service
code remains UI-free, and dialog code never updates controls from a worker.
"""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import threading
from typing import Generic, TypeVar

import wx
from logHandler import log


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

	def __init__(self, max_workers: int = 4) -> None:
		self._executor = ThreadPoolExecutor(
			max_workers=max_workers,
			thread_name_prefix="NVDA-AI-worker",
		)

	def submit(
		self,
		work: Callable[[threading.Event], T],
		*,
		on_success: Callable[[T], None] | None = None,
		on_error: Callable[[Exception], None] | None = None,
		on_finally: Callable[[], None] | None = None,
		is_alive: Callable[[], bool] | None = None,
	) -> TaskHandle[T]:
		cancel_event = threading.Event()

		def dispatch(callback: Callable[[], None]) -> None:
			def guarded_callback() -> None:
				if is_alive is None or is_alive():
					callback()

			UiDispatcher.post(guarded_callback)

		def execute() -> T:
			return work(cancel_event)

		future = self._executor.submit(execute)

		def completed(completed_future: Future[T]) -> None:
			try:
				result = completed_future.result()
			except Exception as error:
				log.error("Background UI task failed: %s", error, exc_info=True)
				if on_error is not None:
					dispatch(lambda: on_error(error))
			else:
				if on_success is not None:
					dispatch(lambda: on_success(result))
			if on_finally is not None:
				dispatch(on_finally)

		future.add_done_callback(completed)
		return TaskHandle(cancel_event, future)


background_tasks = BackgroundTaskRunner()


__all__ = ["BackgroundTaskRunner", "TaskHandle", "UiDispatcher", "background_tasks"]
