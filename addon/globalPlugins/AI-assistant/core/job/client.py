# -*- coding: utf-8 -*-
"""Client Interfaces and In-Memory Mock Implementations for Job Execution.

Defines the abstract JobClient and WorkerClient facades and their corresponding
thread-safe in-memory mock implementations for isolated Tier 1 tests.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import threading
from typing import Any, Callable

from .cancellation import CancellationToken
from .dto import (
	HandshakeResponse,
	JobProgress,
	JobResult,
	JobSnapshot,
	JobSpec,
	JobStatus,
	WorkerHealth,
)
from .protocol import PROTOCOL_VERSION
from .state import JobStateMachine


# ---------------------------------------------------------------------------
# Abstract Client Interfaces
# ---------------------------------------------------------------------------


class JobClient(ABC):
	"""Abstract interface for submitting, tracking, observing, and cancelling compute jobs."""

	@abstractmethod
	def submit_job(self, spec: JobSpec) -> str:
		"""Submit a job specification for execution. Returns job_id."""

	@abstractmethod
	def cancel_job(self, job_id: str, reason: str = "user_cancelled") -> bool:
		"""Request cooperative cancellation of a job. Returns True if acknowledged."""

	@abstractmethod
	def get_job_snapshot(self, job_id: str) -> JobSnapshot | None:
		"""Retrieve a point-in-time snapshot of the job state and history."""

	@abstractmethod
	def list_active_jobs(self) -> tuple[JobSnapshot, ...]:
		"""List snapshots of all currently non-terminal jobs."""

	@abstractmethod
	def subscribe_progress(
		self, job_id: str, callback: Callable[[JobProgress], None]
	) -> Callable[[], None]:
		"""Subscribe to progress updates for a job. Returns an unsubscribe callable."""

	@abstractmethod
	def subscribe_result(
		self, job_id: str, callback: Callable[[JobResult], None]
	) -> Callable[[], None]:
		"""Subscribe to the terminal outcome of a job. Returns an unsubscribe callable."""

	@abstractmethod
	def wait_for_job(self, job_id: str, timeout_seconds: float | None = None) -> JobResult:
		"""Block caller thread until job reaches a terminal state.

		Raises:
			TimeoutError: If timeout expires before job completes.
			KeyError: If job_id is not found.
		"""


class WorkerClient(ABC):
	"""Abstract interface for managing worker connection, health probing, and job client."""

	@abstractmethod
	def connect(self) -> HandshakeResponse:
		"""Establish connection with worker and complete handshake negotiation."""

	@abstractmethod
	def disconnect(self) -> None:
		"""Gracefully disconnect from the worker process."""

	@abstractmethod
	def is_connected(self) -> bool:
		"""Return True if connection is established and handshake was accepted."""

	@abstractmethod
	def poll_health(self) -> WorkerHealth:
		"""Request a current health and resource telemetry snapshot from worker."""

	@abstractmethod
	def get_job_client(self) -> JobClient:
		"""Return the JobClient instance associated with this worker client."""


# ---------------------------------------------------------------------------
# In-Memory Mock Implementations for Isolated Testing
# ---------------------------------------------------------------------------


class MockJobClient(JobClient):
	"""Thread-safe in-memory JobClient executing jobs with synchronous simulation helpers."""

	def __init__(self) -> None:
		self._lock = threading.Lock()
		self._jobs: dict[str, JobStateMachine] = {}
		self._tokens: dict[str, CancellationToken] = {}
		self._progress_subs: dict[str, list[Callable[[JobProgress], None]]] = {}
		self._result_subs: dict[str, list[Callable[[JobResult], None]]] = {}
		self._done_events: dict[str, threading.Event] = {}

	def submit_job(self, spec: JobSpec) -> str:
		"""Register and track a new job specification in SUBMITTED state."""
		with self._lock:
			fsm = JobStateMachine(spec)
			self._jobs[spec.job_id] = fsm
			self._tokens[spec.job_id] = CancellationToken(spec.job_id)
			self._progress_subs.setdefault(spec.job_id, [])
			self._result_subs.setdefault(spec.job_id, [])
			self._done_events[spec.job_id] = threading.Event()
		return spec.job_id

	def cancel_job(self, job_id: str, reason: str = "user_cancelled") -> bool:
		"""Cancel an active job and trigger registered result callbacks."""
		with self._lock:
			fsm = self._jobs.get(job_id)
			if fsm is None:
				return False
			token = self._tokens[job_id]
			token.cancel(reason)

			if not fsm.is_terminal:
				# Advance to RUNNING first if needed, then CANCELLED
				if fsm.state in (JobStatus.SUBMITTED, JobStatus.QUEUED):
					fsm.transition(JobStatus.RUNNING)
				result = JobResult(
					job_id=job_id,
					status=JobStatus.CANCELLED,
					error_message=reason,
					generation=fsm.generation,
				)
				fsm.record_result(result)
				self._done_events[job_id].set()
				callbacks = list(self._result_subs.get(job_id, []))
			else:
				callbacks = []
				result = fsm.result

		if result is not None:
			for cb in callbacks:
				try:
					cb(result)
				except Exception:
					pass
		return True

	def simulate_progress(
		self,
		job_id: str,
		progress_pct: float,
		status_message: str = "",
		bytes_completed: int = 0,
		bytes_total: int = 0,
	) -> None:
		"""Simulate an asynchronous progress update for testing."""
		with self._lock:
			fsm = self._jobs.get(job_id)
			if fsm is None:
				raise KeyError(f"Job '{job_id}' not found")
			progress = JobProgress(
				job_id=job_id,
				status=JobStatus.RUNNING,
				progress_pct=progress_pct,
				status_message=status_message,
				bytes_completed=bytes_completed,
				bytes_total=bytes_total,
				generation=fsm.generation,
			)
			fsm.record_progress(progress)
			callbacks = list(self._progress_subs.get(job_id, []))

		for cb in callbacks:
			try:
				cb(progress)
			except Exception:
				pass

	def simulate_complete(
		self,
		job_id: str,
		result_data: dict[str, Any] | None = None,
		duration_ms: int = 10,
	) -> None:
		"""Simulate successful job completion for testing."""
		with self._lock:
			fsm = self._jobs.get(job_id)
			if fsm is None:
				raise KeyError(f"Job '{job_id}' not found")
			if fsm.state in (JobStatus.SUBMITTED, JobStatus.QUEUED):
				fsm.transition(JobStatus.RUNNING)

			result = JobResult(
				job_id=job_id,
				status=JobStatus.COMPLETED,
				result_data=result_data or {},
				duration_ms=duration_ms,
				generation=fsm.generation,
			)
			fsm.record_result(result)
			self._done_events[job_id].set()
			callbacks = list(self._result_subs.get(job_id, []))

		for cb in callbacks:
			try:
				cb(result)
			except Exception:
				pass

	def simulate_failure(
		self,
		job_id: str,
		error_code: str = "JOB_FAILED",
		error_message: str = "Execution failed",
		retriable: bool = False,
	) -> None:
		"""Simulate job failure for testing."""
		with self._lock:
			fsm = self._jobs.get(job_id)
			if fsm is None:
				raise KeyError(f"Job '{job_id}' not found")
			if fsm.state in (JobStatus.SUBMITTED, JobStatus.QUEUED):
				fsm.transition(JobStatus.RUNNING)

			result = JobResult(
				job_id=job_id,
				status=JobStatus.FAILED,
				error_code=error_code,
				error_message=error_message,
				retriable=retriable,
				generation=fsm.generation,
			)
			fsm.record_result(result)
			self._done_events[job_id].set()
			callbacks = list(self._result_subs.get(job_id, []))

		for cb in callbacks:
			try:
				cb(result)
			except Exception:
				pass

	def get_job_snapshot(self, job_id: str) -> JobSnapshot | None:
		"""Retrieve snapshot for job_id."""
		with self._lock:
			fsm = self._jobs.get(job_id)
			return fsm.snapshot() if fsm is not None else None

	def list_active_jobs(self) -> tuple[JobSnapshot, ...]:
		"""List all active (non-terminal) jobs."""
		with self._lock:
			return tuple(fsm.snapshot() for fsm in self._jobs.values() if not fsm.is_terminal)

	def subscribe_progress(
		self, job_id: str, callback: Callable[[JobProgress], None]
	) -> Callable[[], None]:
		"""Register a callback for progress updates and return an unsubscriber."""
		with self._lock:
			self._progress_subs.setdefault(job_id, []).append(callback)

		def unsubscribe() -> None:
			with self._lock:
				subs = self._progress_subs.get(job_id, [])
				if callback in subs:
					subs.remove(callback)

		return unsubscribe

	def subscribe_result(
		self, job_id: str, callback: Callable[[JobResult], None]
	) -> Callable[[], None]:
		"""Register a callback for terminal results and return an unsubscriber."""
		with self._lock:
			fsm = self._jobs.get(job_id)
			if fsm is not None and fsm.result is not None:
				res = fsm.result
				# Fire immediately if already finished
				callback(res)
				return lambda: None
			self._result_subs.setdefault(job_id, []).append(callback)

		def unsubscribe() -> None:
			with self._lock:
				subs = self._result_subs.get(job_id, [])
				if callback in subs:
					subs.remove(callback)

		return unsubscribe

	def wait_for_job(self, job_id: str, timeout_seconds: float | None = None) -> JobResult:
		"""Wait for job completion or raise TimeoutError."""
		event = self._done_events.get(job_id)
		if event is None:
			raise KeyError(f"Job '{job_id}' not found")
		if not event.wait(timeout_seconds):
			raise TimeoutError(f"Job '{job_id}' did not complete within {timeout_seconds}s timeout")
		with self._lock:
			fsm = self._jobs[job_id]
			if fsm.result is None:
				raise RuntimeError(f"Job '{job_id}' reached done event without a recorded result")
			return fsm.result


class MockWorkerClient(WorkerClient):
	"""Thread-safe in-memory WorkerClient for isolated testing."""

	def __init__(self, worker_pid: int = 12345) -> None:
		self._worker_pid = worker_pid
		self._connected = False
		self._job_client = MockJobClient()
		self._lock = threading.Lock()
		self._health = WorkerHealth(
			worker_pid=worker_pid,
			generation=1,
			uptime_seconds=120.0,
			active_jobs_count=0,
			active_sessions_count=0,
			cpu_percent=1.5,
			rss_memory_bytes=42 * 1024 * 1024,
			is_healthy=True,
		)

	def connect(self) -> HandshakeResponse:
		"""Simulate connecting to worker and completing handshake."""
		with self._lock:
			self._connected = True
			return HandshakeResponse(
				accepted=True,
				protocol_version=PROTOCOL_VERSION,
				worker_pid=self._worker_pid,
				worker_version=PROTOCOL_VERSION,
				negotiated_capabilities=(
					"job.model_download",
					"job.model_verify",
					"job.inference",
					"session.ocr",
					"session.transcription",
				),
				correlation_id="mock_conn_1",
			)

	def disconnect(self) -> None:
		"""Simulate disconnecting from worker."""
		with self._lock:
			self._connected = False

	def is_connected(self) -> bool:
		"""Return simulated connection status."""
		with self._lock:
			return self._connected

	def poll_health(self) -> WorkerHealth:
		"""Return mock worker health status."""
		with self._lock:
			active_jobs = len(self._job_client.list_active_jobs())
			return WorkerHealth(
				worker_pid=self._health.worker_pid,
				generation=self._health.generation,
				uptime_seconds=self._health.uptime_seconds,
				active_jobs_count=active_jobs,
				active_sessions_count=self._health.active_sessions_count,
				cpu_percent=self._health.cpu_percent,
				rss_memory_bytes=self._health.rss_memory_bytes,
				gpu_available=self._health.gpu_available,
				gpu_memory_used_bytes=self._health.gpu_memory_used_bytes,
				gpu_memory_total_bytes=self._health.gpu_memory_total_bytes,
				is_healthy=self._health.is_healthy,
				error_summary=self._health.error_summary,
			)

	def get_job_client(self) -> JobClient:
		"""Return the mock job client."""
		return self._job_client
