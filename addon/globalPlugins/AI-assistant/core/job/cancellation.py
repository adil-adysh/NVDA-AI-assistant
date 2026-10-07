# -*- coding: utf-8 -*-
"""Deterministic Two-Phase Cancellation Contract for Out-of-Process Tasks.

Enforces Invariant A22:
- Phase 1: Fine-grained cooperative yield checks via CancellationToken (<100ms exit SLA).
- Phase 2: CancellationCoordinator managing 3.0s supervisor preemption deadlines.
"""

from __future__ import annotations

import threading
import time
from typing import Callable


class JobCancelledError(Exception):
	"""Raised when a task detects that cooperative cancellation has been signaled."""

	def __init__(self, job_id: str, reason: str = "cancelled") -> None:
		super().__init__(f"Job '{job_id}' was cancelled: {reason}")
		self.job_id = job_id
		self.reason = reason


# Canonical alias matching Section 15.2 of the architecture deliverable
JobCancelledException = JobCancelledError


class CancellationToken:
	"""Thread-safe cooperative cancellation token evaluated at fine-grained yield points."""

	def __init__(self, job_id: str) -> None:
		self._job_id = job_id
		self._event = threading.Event()
		self._reason: str = ""
		self._cancelled_at_epoch_ms: int = 0
		self._callbacks: list[Callable[[], None]] = []
		self._lock = threading.Lock()

	@property
	def job_id(self) -> str:
		"""Return the job ID this token belongs to."""
		return self._job_id

	@property
	def is_cancelled(self) -> bool:
		"""Return True if cancellation has been requested."""
		return self._event.is_set()

	@property
	def reason(self) -> str:
		"""Return the cancellation reason message, if cancelled."""
		with self._lock:
			return self._reason

	@property
	def cancelled_at_epoch_ms(self) -> int:
		"""Return epoch ms timestamp when cancel was signaled, or 0."""
		with self._lock:
			return self._cancelled_at_epoch_ms

	def cancel(self, reason: str = "user_cancelled") -> None:
		"""Signal cancellation to any thread evaluating this token and fire callbacks."""
		with self._lock:
			if not self._event.is_set():
				self._reason = reason
				self._cancelled_at_epoch_ms = int(time.time() * 1000)
				self._event.set()
				callbacks_to_fire = list(self._callbacks)
			else:
				callbacks_to_fire = []

		for callback in callbacks_to_fire:
			try:
				callback()
			except Exception:
				# Callbacks must never disrupt cooperative cancellation signal
				pass

	def check_cancelled(self) -> None:
		"""Cooperative yield point: raise JobCancelledError if cancelled.

		Call this at iteration steps: every 64 KB download block, every file extraction,
		every inference token, or between frame inspections.
		"""
		if self._event.is_set():
			with self._lock:
				reason = self._reason
			raise JobCancelledError(self._job_id, reason)

	def throw_if_cancelled(self) -> None:
		"""Alias for check_cancelled()."""
		self.check_cancelled()

	def register_callback(self, callback: Callable[[], None]) -> None:
		"""Register a callback to run on cancellation.

		If already cancelled, invokes callback immediately.
		"""
		with self._lock:
			already_cancelled = self._event.is_set()
			if not already_cancelled:
				self._callbacks.append(callback)

		if already_cancelled:
			try:
				callback()
			except Exception:
				pass

	def wait(self, timeout_seconds: float | None = None) -> bool:
		"""Block until cancellation is requested or timeout expires. Returns is_set()."""
		return self._event.wait(timeout_seconds)


class CancellationCoordinator:
	"""Two-phase cancellation coordinator tracking job tokens and preemption escalation deadlines."""

	def __init__(self) -> None:
		self._tokens: dict[str, CancellationToken] = {}
		self._deadlines: dict[str, float] = {}
		self._lock = threading.RLock()

	def register_token(self, job_id: str) -> CancellationToken:
		"""Create and register a new CancellationToken for job_id."""
		with self._lock:
			token = CancellationToken(job_id)
			self._tokens[job_id] = token
			return token

	def get_token(self, job_id: str) -> CancellationToken | None:
		"""Retrieve the registered CancellationToken for job_id, or None."""
		with self._lock:
			return self._tokens.get(job_id)

	def unregister_token(self, job_id: str) -> None:
		"""Remove the token and preemption deadline for job_id."""
		with self._lock:
			self._tokens.pop(job_id, None)
			self._deadlines.pop(job_id, None)

	def request_cancellation(
		self,
		job_id: str,
		reason: str = "user_cancelled",
		preemption_timeout: float = 3.0,
	) -> bool:
		"""Trigger Phase 1 cooperative cancellation and arm the Phase 2 preemption deadline.

		Returns:
			True if token was found and cancellation signaled, False otherwise.
		"""
		with self._lock:
			token = self._tokens.get(job_id)
			if token is None:
				return False
			self._deadlines[job_id] = time.monotonic() + preemption_timeout

		token.cancel(reason)
		return True

	def is_preemption_due(self, job_id: str) -> bool:
		"""Return True if Phase 1 was requested and the Phase 2 preemption deadline has expired."""
		with self._lock:
			deadline = self._deadlines.get(job_id)
			if deadline is None:
				return False
			return time.monotonic() >= deadline

	def get_preemption_deadline(self, job_id: str) -> float | None:
		"""Return the monotonic deadline timestamp for job_id, or None if not cancelled."""
		with self._lock:
			return self._deadlines.get(job_id)

	def cancel_all(
		self,
		reason: str = "system_shutdown",
		preemption_timeout: float = 3.0,
	) -> None:
		"""Cancel all active tokens tracked by this coordinator."""
		deadline = time.monotonic() + preemption_timeout
		with self._lock:
			tokens = list(self._tokens.values())
			for job_id in self._tokens:
				self._deadlines[job_id] = deadline
		for token in tokens:
			token.cancel(reason)
