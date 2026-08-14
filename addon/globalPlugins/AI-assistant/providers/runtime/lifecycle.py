# -*- coding: utf-8 -*-
"""Shared managed-server readiness behavior."""

from __future__ import annotations

import time
from collections.abc import Callable


def wait_for_server_ready(
	*,
	is_running: Callable[[], bool],
	is_adopted: Callable[[], bool],
	is_healthy: Callable[[float], bool],
	stop: Callable[[], None],
	timeout: float,
	interval: float,
	on_progress: Callable[[str], None] | None = None,
	progress_message: str,
	exit_message: str,
	log_timeout: Callable[[float], None] | None = None,
) -> bool:
	"""Apply the common start/readiness/cleanup contract to a server."""
	deadline = time.monotonic() + timeout
	while time.monotonic() < deadline:
		if not is_running() and not is_adopted():
			raise RuntimeError(exit_message)
		if is_healthy(min(2.0, max(0.1, deadline - time.monotonic()))):
			return True
		if on_progress:
			on_progress(progress_message)
		time.sleep(interval)
	if log_timeout:
		log_timeout(timeout)
	if is_running() and not is_adopted():
		stop()
	return False
