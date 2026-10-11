# -*- coding: utf-8 -*-
"""Non-blocking NVDA-startup orchestration for managed local providers."""

from __future__ import annotations

import threading
from collections.abc import Callable


MANAGED_LOCAL_PROVIDERS = frozenset({"litert-lm", "llama-cpp-server"})


def schedule_active_local_provider_start(
	*,
	provider: str,
	litert_enabled: bool = False,
	llama_enabled: bool = False,
	litert_installed: bool,
	ensure_ready: Callable[[], None],
	report_error: Callable[[Exception, str], None],
	startup_mode: str | None = None,
	prepare_worker: Callable[[], object] | None = None,
	thread_factory: Callable[..., threading.Thread] = threading.Thread,
) -> threading.Thread | None:
	"""Schedule startup for the active managed provider when policy permits.

	Worker preparation only connects the owned worker. Server startup enters
	the normal readiness path, which owns health and startup fingerprint
	validation and will reuse, adopt, or replace a live server as appropriate.
	"""
	provider = str(provider or "").strip().lower()
	if provider not in MANAGED_LOCAL_PROVIDERS:
		return None
	if startup_mode is None:
		enabled = litert_enabled if provider == "litert-lm" else llama_enabled
		startup_mode = "server" if enabled else "lazy"
	if startup_mode not in {"worker", "server"}:
		return None
	if startup_mode == "server" and provider == "litert-lm" and not litert_installed:
		return None
	operation = prepare_worker if startup_mode == "worker" else ensure_ready
	if operation is None:
		raise ValueError("Worker startup requires a worker preparation callback")

	def start_server() -> None:
		try:
			operation()
		except Exception as error:  # Startup failure must never abort NVDA initialization.
			report_error(error, provider)

	thread = thread_factory(
		target=start_server,
		name=f"{provider}{'Worker' if startup_mode == 'worker' else 'Server'}AutoStart",
		daemon=True,
	)
	thread.start()
	return thread
