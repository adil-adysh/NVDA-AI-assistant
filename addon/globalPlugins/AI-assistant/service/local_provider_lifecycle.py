"""Application policy for switching managed runtimes; native workers own processes."""
from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from ..core.cancellation import RequestCancelled
from ..core.runtime_selection import RuntimeSelectionGate

log = logging.getLogger(__name__)


class LocalProviderLifecycle:
	"""Serialize startup with provider changes without blocking the NVDA thread.

	Callers dispatch operations off-thread. Stop callbacks must use the owned
	worker supervisors, which fence launches and never kill adopted servers.
	"""

	def __init__(self, *, get_provider: Callable[[], str], stop_servers: Mapping[str, Callable[[], object]]) -> None:
		self._stop_servers = dict(stop_servers)
		self.gate = RuntimeSelectionGate(get_provider)

	def run_selected(self, provider: str, operation: Callable[[], object]) -> None:
		def reconcile() -> None:
			for runtime, stop in self._stop_servers.items():
				if runtime != provider:
					try:
						stop()
					except Exception:
						log.exception("Unable to stop inactive managed runtime %s", runtime)
			if self.gate.is_selected(provider):
				operation()
		try:
			self.gate.run(provider, reconcile)
		except RequestCancelled:
			return

	def close(self) -> None:
		# Shutdown_worker_owner supplies the authoritative native launch fence.
		self.gate.close()
