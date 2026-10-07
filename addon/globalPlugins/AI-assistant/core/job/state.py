# -*- coding: utf-8 -*-
"""Finite State Machines for Discrete Jobs and Continuous Streaming Sessions.

Enforces Invariant A21 (monotonic discrete job progression and single-result invariant)
and Invariant A23 (continuous session streaming FSM with generation fencing).
"""

from __future__ import annotations

import threading
import time

from .dto import (
	JobProgress,
	JobResult,
	JobSnapshot,
	JobSpec,
	JobStatus,
	SessionConfig,
	SessionState,
)


class InvalidStateTransitionError(ValueError):
	"""Raised when an illegal state progression is attempted."""


class TerminalStateError(InvalidStateTransitionError):
	"""Raised when attempting to transition or mutate a state machine in a terminal state."""


# ---------------------------------------------------------------------------
# Discrete Job Finite State Machine (Invariant A21)
# ---------------------------------------------------------------------------

_VALID_JOB_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
	JobStatus.SUBMITTED: frozenset({
		JobStatus.QUEUED,
		JobStatus.RUNNING,
		JobStatus.CANCELLED,
		JobStatus.FAILED,
	}),
	JobStatus.QUEUED: frozenset({
		JobStatus.RUNNING,
		JobStatus.CANCELLED,
		JobStatus.FAILED,
	}),
	JobStatus.RUNNING: frozenset({
		JobStatus.RUNNING,  # Self-transition for progress updates
		JobStatus.COMPLETED,
		JobStatus.FAILED,
		JobStatus.CANCELLED,
	}),
	JobStatus.COMPLETED: frozenset(),
	JobStatus.FAILED: frozenset(),
	JobStatus.CANCELLED: frozenset(),
}


class JobStateMachine:
	"""Monotonic discrete job state machine with generation fencing and single-result invariant."""

	def __init__(self, spec: JobSpec) -> None:
		self._spec = spec
		self._state = JobStatus.SUBMITTED
		self._generation = spec.generation
		self._progress: JobProgress | None = None
		self._result: JobResult | None = None
		self._created_at_epoch_ms = int(time.time() * 1000)
		self._updated_at_epoch_ms = self._created_at_epoch_ms
		self._lock = threading.Lock()

	@property
	def job_id(self) -> str:
		"""Return the unique job identifier."""
		return self._spec.job_id

	@property
	def state(self) -> JobStatus:
		"""Return the current job status."""
		with self._lock:
			return self._state

	@property
	def generation(self) -> int:
		"""Return the current active generation."""
		with self._lock:
			return self._generation

	@property
	def is_terminal(self) -> bool:
		"""Return True if the job has reached a terminal state."""
		with self._lock:
			return self._state.is_terminal

	@property
	def result(self) -> JobResult | None:
		"""Return the terminal JobResult, or None if not finished."""
		with self._lock:
			return self._result

	@property
	def progress(self) -> JobProgress | None:
		"""Return the latest JobProgress, or None if none recorded."""
		with self._lock:
			return self._progress

	def transition(self, next_state: JobStatus, generation: int | None = None) -> None:
		"""Transition the job to next_state following monotonic rules and generation fencing.

		Raises:
			TerminalStateError: If the job is already in a terminal state.
			InvalidStateTransitionError: If the transition is illegal or generation is stale.
		"""
		with self._lock:
			if generation is not None and generation < self._generation:
				raise InvalidStateTransitionError(
					f"Cannot transition job '{self.job_id}': stale generation "
					f"{generation} < active generation {self._generation}"
				)

			if self._state.is_terminal:
				raise TerminalStateError(
					f"Cannot transition job '{self.job_id}' from terminal state "
					f"'{self._state}' to '{next_state}'"
				)

			allowed = _VALID_JOB_TRANSITIONS.get(self._state, frozenset())
			if next_state not in allowed:
				raise InvalidStateTransitionError(
					f"Illegal state transition for job '{self.job_id}' "
					f"from '{self._state}' to '{next_state}'"
				)

			self._state = next_state
			self._updated_at_epoch_ms = int(time.time() * 1000)
			if generation is not None and generation > self._generation:
				self._generation = generation

	def record_progress(self, progress: JobProgress) -> None:
		"""Update transient progress telemetry, enforcing generation fencing and running state.

		Raises:
			TerminalStateError: If the job is already terminal.
			InvalidStateTransitionError: If progress generation is stale.
		"""
		with self._lock:
			if progress.generation < self._generation:
				raise InvalidStateTransitionError(
					f"Stale progress generation {progress.generation} < {self._generation}"
				)

			if self._state.is_terminal:
				raise TerminalStateError(
					f"Cannot record progress for terminal job '{self.job_id}' (state: '{self._state}')"
				)

			# Auto-advance to RUNNING if currently SUBMITTED or QUEUED
			if self._state in (JobStatus.SUBMITTED, JobStatus.QUEUED):
				self._state = JobStatus.RUNNING

			self._progress = progress
			self._updated_at_epoch_ms = int(time.time() * 1000)
			if progress.generation > self._generation:
				self._generation = progress.generation

	def record_result(self, result: JobResult) -> None:
		"""Record the single terminal JobResult, transitioning the job to terminal state.

		Enforces the single-result invariant (exactly one terminal JobResult per job).

		Raises:
			TerminalStateError: If a result was already recorded or the job is already terminal.
			InvalidStateTransitionError: If result generation is stale.
		"""
		with self._lock:
			if result.generation < self._generation:
				raise InvalidStateTransitionError(
					f"Stale result generation {result.generation} < active {self._generation}"
				)

			if self._result is not None or self._state.is_terminal:
				raise TerminalStateError(
					f"Cannot record result for job '{self.job_id}': result already set "
					f"(single-result invariant) in state '{self._state}'"
				)

			allowed = _VALID_JOB_TRANSITIONS.get(self._state, frozenset())
			if result.status not in allowed:
				raise InvalidStateTransitionError(
					f"Cannot transition job '{self.job_id}' from '{self._state}' "
					f"to result status '{result.status}'"
				)

			self._state = result.status
			self._result = result
			self._updated_at_epoch_ms = int(time.time() * 1000)
			if result.generation > self._generation:
				self._generation = result.generation

	def snapshot(self) -> JobSnapshot:
		"""Produce a point-in-time immutable snapshot of this job state machine."""
		with self._lock:
			return JobSnapshot(
				spec=self._spec,
				state=self._state,
				progress=self._progress,
				result=self._result,
				created_at_epoch_ms=self._created_at_epoch_ms,
				updated_at_epoch_ms=self._updated_at_epoch_ms,
			)


# ---------------------------------------------------------------------------
# Continuous Streaming Session Finite State Machine (Invariant A23)
# ---------------------------------------------------------------------------

_VALID_SESSION_TRANSITIONS: dict[SessionState, frozenset[SessionState]] = {
	SessionState.INIT: frozenset({
		SessionState.CONFIGURING,
		SessionState.ERROR,
	}),
	SessionState.CONFIGURING: frozenset({
		SessionState.READY,
		SessionState.ERROR,
	}),
	SessionState.READY: frozenset({
		SessionState.STREAMING,
		SessionState.PAUSED,
		SessionState.CLOSING,
		SessionState.ERROR,
	}),
	SessionState.STREAMING: frozenset({
		SessionState.STREAMING,  # Self-transition during active streaming
		SessionState.PAUSED,
		SessionState.CLOSING,
		SessionState.ERROR,
	}),
	SessionState.PAUSED: frozenset({
		SessionState.STREAMING,
		SessionState.CLOSING,
		SessionState.ERROR,
	}),
	SessionState.CLOSING: frozenset({
		SessionState.CLOSED,
		SessionState.ERROR,
	}),
	SessionState.CLOSED: frozenset(),
	SessionState.ERROR: frozenset(),
}


class SessionStateMachine:
	"""Continuous streaming session finite state machine (OCR, Transcription)."""

	def __init__(self, config: SessionConfig) -> None:
		self._config = config
		self._state = SessionState.INIT
		self._generation = config.generation
		self._lock = threading.Lock()

	@property
	def session_id(self) -> str:
		"""Return the unique session identifier."""
		return self._config.session_id

	@property
	def state(self) -> SessionState:
		"""Return the current session state."""
		with self._lock:
			return self._state

	@property
	def generation(self) -> int:
		"""Return the active generation."""
		with self._lock:
			return self._generation

	@property
	def is_terminal(self) -> bool:
		"""Return True if the session has terminated."""
		with self._lock:
			return self._state.is_terminal

	def transition(self, next_state: SessionState, generation: int | None = None) -> None:
		"""Transition the session to next_state.

		Raises:
			TerminalStateError: If the session is already in a terminal state (CLOSED or ERROR).
			InvalidStateTransitionError: If the transition is illegal or generation is stale.
		"""
		with self._lock:
			if generation is not None and generation < self._generation:
				raise InvalidStateTransitionError(
					f"Cannot transition session '{self.session_id}': stale generation "
					f"{generation} < active generation {self._generation}"
				)

			if self._state.is_terminal:
				raise TerminalStateError(
					f"Cannot transition session '{self.session_id}' from terminal state "
					f"'{self._state}' to '{next_state}'"
				)

			allowed = _VALID_SESSION_TRANSITIONS.get(self._state, frozenset())
			if next_state not in allowed:
				raise InvalidStateTransitionError(
					f"Illegal state transition for session '{self.session_id}' "
					f"from '{self._state}' to '{next_state}'"
				)

			self._state = next_state
			if generation is not None and generation > self._generation:
				self._generation = generation
