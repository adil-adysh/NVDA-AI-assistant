# -*- coding: utf-8 -*-
"""Non-blocking NVDA-startup orchestration for managed local providers."""

from __future__ import annotations

import threading
from collections.abc import Callable


MANAGED_LOCAL_PROVIDERS = frozenset({"litert-lm", "llama-cpp-server"})


def schedule_active_local_provider_start(
	*,
	provider: str,
	litert_installed: bool,
	ensure_ready: Callable[[], None],
	report_error: Callable[[Exception, str], None],
	startup_mode: str = "lazy",
	should_start: Callable[[], bool] | None = None,
	thread_factory: Callable[..., threading.Thread] = threading.Thread,
) -> threading.Thread | None:
	"""Schedule startup for the active managed provider when policy permits.

	Server startup enters the normal readiness path, which owns health and
	startup fingerprint validation and reuses, adopts or replaces live servers.
	"""
	provider = str(provider or "").strip().lower()
	if provider not in MANAGED_LOCAL_PROVIDERS:
		return None
	if startup_mode != "server":
		return None
	if provider == "litert-lm" and not litert_installed:
		return None

	def start_server() -> None:
		try:
			if should_start is not None and not should_start():
				return
			ensure_ready()
		except Exception as error:  # Startup failure must never abort NVDA initialization.
			report_error(error, provider)

	thread = thread_factory(
		target=start_server,
		name=f"{provider}ServerAutoStart",
		daemon=True,
	)
	thread.start()
	return thread
