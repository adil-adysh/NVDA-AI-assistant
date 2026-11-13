"""Route MCP provider operations through the private worker's runtime jobs."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


class _CancellationProbe:
	"""Adapt ToolCallContext's probe to WorkerClient's event-shaped argument."""

	def __init__(self, cancelled: Callable[[], bool]) -> None:
		self._cancelled = cancelled

	def is_set(self) -> bool:
		return self._cancelled()


def dispatch_mcp_worker_command(
	frame: dict[str, Any],
	timeout: float,
	cancellation_requested: Callable[[], bool],
) -> dict[str, Any]:
	"""Submit one MCP manager operation as a worker job, off NVDA's UI thread."""
	from ..plugin.worker_supervisor import ensure_worker_client

	client = ensure_worker_client()
	return client.run_job(
		"runtime_command",
		frame,
		timeout=max(0.1, min(float(timeout), 300.0)),
		cancel_event=_CancellationProbe(cancellation_requested),
	)
