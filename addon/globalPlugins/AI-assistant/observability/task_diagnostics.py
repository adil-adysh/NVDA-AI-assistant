"""Optional asynchronous file diagnostics adapter for application tasks."""
from collections.abc import Callable
import logging
from queue import Empty, Full, Queue
import threading

from .events import DiagnosticEvent
from .reporter import MetricsReporter

log = logging.getLogger(__name__)


class _AsyncDiagnosticWriter:
	"""Keep optional diagnostic file IO off UI and task-completion threads."""

	IDLE_TIMEOUT = 30.0

	def __init__(self, write_event: Callable[[object], None], max_pending: int = 512) -> None:
		self._write_event = write_event
		self._queue: Queue[object] = Queue(maxsize=max_pending)
		self._lock = threading.Lock()
		self._thread: threading.Thread | None = None

	def submit(self, event: object) -> bool:
		with self._lock:
			if self._thread is None:
				self._thread = threading.Thread(
					target=self._run,
					name="NVDA-AI-diagnostics",
					daemon=True,
				)
				self._thread.start()
			try:
				self._queue.put_nowait(event)
			except Full:
				log.debug("Dropping diagnostic event because the writer queue is full")
				return False
			return True

	def flush(self) -> None:
		"""Wait for queued events; intended for deterministic tests and shutdown."""
		self._queue.join()

	def _run(self) -> None:
		while True:
			try:
				event = self._queue.get(timeout=self.IDLE_TIMEOUT)
			except Empty:
				with self._lock:
					if self._queue.empty():
						self._thread = None
						return
				continue
			try:
				self._write_event(event)
			except Exception:
				log.debug("Unable to write queued diagnostic event", exc_info=True)
			finally:
				self._queue.task_done()


class AsyncTaskDiagnostics:
	def __init__(self, reporter: MetricsReporter) -> None:
		self._reporter = reporter
		self._writer = _AsyncDiagnosticWriter(reporter.report_event)

	def emit(self, event: str, operation_id: str, **attributes: object) -> None:
		if self._reporter.is_enabled():
			self._writer.submit(DiagnosticEvent(event, operation_id=operation_id, attributes=attributes))

	def flush(self) -> None:
		self._writer.flush()
