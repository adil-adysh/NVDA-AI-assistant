# -*- coding: utf-8 -*-
from __future__ import annotations

from enum import Enum
from threading import RLock
from typing import Callable


class HostLifecycleState(str, Enum):
	STOPPED = "stopped"
	STARTING = "starting"
	READY = "ready"
	HIDDEN = "hidden"
	FAILED = "failed"


class HostLifecycleService:
	def __init__(self) -> None:
		self._lock = RLock()
		self._state = HostLifecycleState.STOPPED

	@property
	def state(self) -> HostLifecycleState:
		with self._lock:
			return self._state

	def prepare_primary_action(self) -> None:
		with self._lock:
			if self._state == HostLifecycleState.FAILED:
				self._state = HostLifecycleState.STOPPED

	def ensure_started(
		self,
		starter: Callable[[], None],
		alive_check: Callable[[], bool] | None = None,
	) -> None:
		with self._lock:
			if self._state in {HostLifecycleState.READY, HostLifecycleState.HIDDEN}:
				if alive_check is not None and not alive_check():
					self._state = HostLifecycleState.STOPPED
				else:
					return
			self._state = HostLifecycleState.STARTING
		try:
			starter()
		except Exception:
			self.mark_failed()
			raise

	def mark_ready(self) -> None:
		with self._lock:
			self._state = HostLifecycleState.READY

	def mark_hidden(self) -> None:
		with self._lock:
			if self._state != HostLifecycleState.FAILED:
				self._state = HostLifecycleState.HIDDEN

	def mark_host_closed(self) -> None:
		self.mark_hidden()

	def mark_failed(self) -> None:
		with self._lock:
			self._state = HostLifecycleState.FAILED

	def mark_stopped(self) -> None:
		with self._lock:
			self._state = HostLifecycleState.STOPPED

	def mark_command_succeeded(self, command_name: str) -> None:
		if command_name == "close_window":
			self.mark_hidden()
			return
		self.mark_ready()

	def should_dispatch_background_command(self) -> bool:
		return self.state == HostLifecycleState.READY
