"""Request-scoped preparation feedback, separate from runtime lifecycle ownership."""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

try:
	from .translation import _
except ImportError:
	from core.translation import _  # type: ignore[no-redef]

log = logging.getLogger(__name__)
T = TypeVar("T")


class ReadinessProgress:
	def __init__(self, report: Callable[[str], None], on_stage: Callable[[str], None] | None = None) -> None:
		self.report = report
		self.on_stage = on_stage
		self.started = False
		self.delayed = False

	def update(self, status: Any, elapsed: float) -> None:
		state = status.get("state") if isinstance(status, dict) else getattr(status, "state", None)
		if state in {"starting", "restarting"} and not self.started:
			self.started = True
			self.emit(state)
		if elapsed >= 10 and not self.delayed:
			self.delayed = True
			self.emit("delayed")

	def emit(self, stage: str) -> None:
		if self.on_stage:
			self.on_stage(stage)
		else:
			self.report(render_readiness_stage(stage))


def render_readiness_stage(stage: str) -> str:
	return {
		"starting": _("Starting local AI server…"),
		"restarting": _("Restarting local AI server…"),
		"delayed": _("Still preparing local AI. Please wait."),
	}.get(stage, "")


def run_with_readiness_progress(
	operation: Callable[[], T],
	on_progress: Callable[[str], None] | None,
	status: Callable[[], Any] | None = None,
	on_stage: Callable[[str], None] | None = None,
) -> T:
	"""Observe native snapshots and emit request-scoped preparation stages.

	Never query the command pipe while a readiness command owns it. Native
	status snapshots are nonblocking and expose actual lifecycle transitions.
	The observer is stopped and joined before completion/error is returned.
	"""
	if on_progress is None:
		return operation()
	finished = threading.Event()
	policy = ReadinessProgress(on_progress, on_stage)
	started_at = time.monotonic()

	def observe() -> None:
		while not finished.wait(0.1):
			try:
				snapshot = status() if status else None
				if not finished.is_set():
					policy.update(snapshot, time.monotonic() - started_at)
			except Exception:
				log.debug("Readiness progress observer failed", exc_info=True)

	thread = threading.Thread(target=observe, name="AIReadinessProgress", daemon=True)
	thread.start()
	try:
		return operation()
	finally:
		finished.set()
		thread.join()
