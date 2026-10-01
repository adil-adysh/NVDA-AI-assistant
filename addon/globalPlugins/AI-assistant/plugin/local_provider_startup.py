# -*- coding: utf-8 -*-
"""Non-blocking NVDA-startup orchestration for managed local providers."""

from __future__ import annotations

import threading
from collections.abc import Callable


MANAGED_LOCAL_PROVIDERS = frozenset({"litert-lm", "llama-cpp-server"})


def schedule_active_local_provider_start(
	*,
	provider: str,
	litert_enabled: bool,
	llama_enabled: bool,
	litert_installed: bool,
	ensure_ready: Callable[[], None],
	report_error: Callable[[Exception, str], None],
	thread_factory: Callable[..., threading.Thread] = threading.Thread,
) -> threading.Thread | None:
	"""Schedule startup for the active managed provider when policy permits.

	The worker always enters the normal readiness path. In particular, a live
	LiteRT process is not skipped here: readiness owns health and startup
	fingerprint validation and will reuse, adopt, or replace it as appropriate.
	"""
	provider = str(provider or "").strip().lower()
	if provider not in MANAGED_LOCAL_PROVIDERS:
		return None
	if provider == "litert-lm" and (not litert_enabled or not litert_installed):
		return None
	if provider == "llama-cpp-server" and not llama_enabled:
		return None

	def start_server() -> None:
		try:
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
