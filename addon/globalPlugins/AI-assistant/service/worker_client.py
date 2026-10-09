# -*- coding: utf-8 -*-
"""Named Pipe Client implementations of JobClient and WorkerClient interfaces.

Enforces Invariant A18 (bi-directional named pipe transport),
Invariant A21 (job lifecycle tracking and snapshot queries),
Invariant A22 (two-phase cooperative cancellation), and
Invariant A24 (immutable DTOs and pure Python isolation).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable

try:
	from ..core.job.client import JobClient, WorkerClient
	from ..core.job.dto import (
		HandshakeRequest,
		HandshakeResponse,
		JobProgress,
		JobResult,
		JobSnapshot,
		JobSpec,
		JobStatus,
		WorkerHealth,
	)
	from ..core.job.protocol import PROTOCOL_VERSION
	from ..worker.ipc.transport import NamedPipeClient, PipeDisconnectedError
except (ImportError, ValueError):
	from core.job.client import (  # type: ignore[no-redef]
		JobClient,
		WorkerClient,
	)
	from core.job.dto import (  # type: ignore[no-redef]
		HandshakeRequest,
		HandshakeResponse,
		JobProgress,
		JobResult,
		JobSnapshot,
		JobSpec,
		JobStatus,
		WorkerHealth,
	)
	from core.job.protocol import PROTOCOL_VERSION  # type: ignore[no-redef]
	from worker.ipc.transport import (  # type: ignore[no-redef]
		NamedPipeClient,
		PipeDisconnectedError,
	)

logger = logging.getLogger(__name__)


class NamedPipeJobClient(JobClient):
	"""JobClient implementation communicating over Named Pipe transport."""

	def __init__(
		self,
		cmd_client: NamedPipeClient,
		evt_client: NamedPipeClient,
		cmd_lock: threading.Lock | None = None,
	) -> None:
		self._cmd_client = cmd_client
		self._evt_client = evt_client
		self._cmd_lock = cmd_lock or threading.Lock()

		self._snapshots: dict[str, JobSnapshot] = {}
		self._result_events: dict[str, threading.Event] = {}
		self._results: dict[str, JobResult] = {}
		self._progress_callbacks: dict[str, list[Callable[[JobProgress], None]]] = {}
		self._result_callbacks: dict[str, list[Callable[[JobResult], None]]] = {}
		self._lock = threading.Lock()

		self._running = True
		self._evt_listener_thread = threading.Thread(
			target=self._run_evt_listener,
			name="NamedPipeJobClientEvtListener",
			daemon=True,
		)
		self._evt_listener_thread.start()

	def _run_evt_listener(self) -> None:
		"""Background thread continuously consuming updates from event pipe."""
		while self._running:
			try:
				if not self._evt_client.is_connected:
					time.sleep(0.05)
					continue
				frame = self._evt_client.read_frame()
				self._handle_event_frame(frame)
			except PipeDisconnectedError:
				logger.debug("Event pipe disconnected in JobClient")
				break
			except Exception as exc:
				if not self._running:
					break
				logger.error("Error in JobClient event listener: %s", exc)

	def _handle_event_frame(self, frame: dict[str, Any]) -> None:
		"""Process an incoming event frame (JobUpdate or JobResult)."""
		frame_type = str(frame.get("type", ""))

		if frame_type == "job_update":
			progress = JobProgress.from_dict(frame)
			job_id = progress.job_id
			with self._lock:
				snap = self._snapshots.get(job_id)
				if snap:
					self._snapshots[job_id] = JobSnapshot(
						spec=snap.spec,
						state=progress.status,
						progress=progress,
						result=snap.result,
						created_at_epoch_ms=snap.created_at_epoch_ms,
						updated_at_epoch_ms=int(time.time() * 1000),
					)
				callbacks = list(self._progress_callbacks.get(job_id, []))

			for cb in callbacks:
				try:
					cb(progress)
				except Exception as exc:
					logger.error("Error in progress callback for %s: %s", job_id, exc)

		elif frame_type == "job_result":
			result = JobResult.from_dict(frame)
			job_id = result.job_id
			with self._lock:
				self._results[job_id] = result
				snap = self._snapshots.get(job_id)
				if snap:
					self._snapshots[job_id] = JobSnapshot(
						spec=snap.spec,
						state=result.status,
						progress=snap.progress,
						result=result,
						created_at_epoch_ms=snap.created_at_epoch_ms,
						updated_at_epoch_ms=int(time.time() * 1000),
					)
				evt = self._result_events.get(job_id)
				if evt:
					evt.set()
				callbacks = list(self._result_callbacks.get(job_id, []))

			for cb in callbacks:
				try:
					cb(result)
				except Exception as exc:
					logger.error("Error in result callback for %s: %s", job_id, exc)

	def submit_job(self, spec: JobSpec) -> str:
		"""Submit a job specification over the command pipe."""
		with self._lock:
			self._snapshots[spec.job_id] = JobSnapshot(
				spec=spec,
				state=JobStatus.SUBMITTED,
				created_at_epoch_ms=int(time.time() * 1000),
				updated_at_epoch_ms=int(time.time() * 1000),
			)
			self._result_events[spec.job_id] = threading.Event()

		with self._cmd_lock:
			self._cmd_client.write_frame(spec.to_dict())
			ack = self._cmd_client.read_frame()

		if ack.get("type") != "job_ack" or ack.get("status") != "accepted":
			err_msg = ack.get("error_message", "Job submission rejected")
			raise RuntimeError(f"Submission failed for {spec.job_id}: {err_msg}")

		with self._lock:
			snap = self._snapshots.get(spec.job_id)
			if snap:
				self._snapshots[spec.job_id] = JobSnapshot(
					spec=snap.spec,
					state=JobStatus.QUEUED,
					created_at_epoch_ms=snap.created_at_epoch_ms,
					updated_at_epoch_ms=int(time.time() * 1000),
				)

		return spec.job_id

	def cancel_job(self, job_id: str, reason: str = "user_cancelled") -> bool:
		"""Request cooperative cancellation of a job."""
		with self._cmd_lock:
			self._cmd_client.write_frame(
				{
					"type": "job_cancellation_request",
					"job_id": job_id,
					"reason": reason,
				}
			)
			ack = self._cmd_client.read_frame()

		return bool(ack.get("accepted", False))

	def get_job_snapshot(self, job_id: str) -> JobSnapshot | None:
		"""Retrieve a point-in-time snapshot of the job state."""
		with self._lock:
			return self._snapshots.get(job_id)

	def list_active_jobs(self) -> tuple[JobSnapshot, ...]:
		"""List snapshots of all currently active (non-terminal) jobs."""
		with self._lock:
			return tuple(s for s in self._snapshots.values() if not s.is_terminal)

	def subscribe_progress(
		self, job_id: str, callback: Callable[[JobProgress], None]
	) -> Callable[[], None]:
		"""Subscribe to progress updates for a job."""
		with self._lock:
			self._progress_callbacks.setdefault(job_id, []).append(callback)

		def unsubscribe() -> None:
			with self._lock:
				cbs = self._progress_callbacks.get(job_id)
				if cbs and callback in cbs:
					cbs.remove(callback)

		return unsubscribe

	def subscribe_result(
		self, job_id: str, callback: Callable[[JobResult], None]
	) -> Callable[[], None]:
		"""Subscribe to the terminal outcome of a job."""
		with self._lock:
			self._result_callbacks.setdefault(job_id, []).append(callback)

		def unsubscribe() -> None:
			with self._lock:
				cbs = self._result_callbacks.get(job_id)
				if cbs and callback in cbs:
					cbs.remove(callback)

		return unsubscribe

	def wait_for_job(
		self, job_id: str, timeout_seconds: float | None = None
	) -> JobResult:
		"""Block until job reaches terminal outcome or timeout expires."""
		with self._lock:
			if job_id in self._results:
				return self._results[job_id]
			evt = self._result_events.get(job_id)
			if not evt:
				raise KeyError(f"Job {job_id} not found")

		finished = evt.wait(timeout=timeout_seconds)
		if not finished:
			raise TimeoutError(
				f"Timed out waiting for job {job_id} after {timeout_seconds}s"
			)

		with self._lock:
			res = self._results.get(job_id)
			if not res:
				raise RuntimeError(
					f"Job {job_id} signaled completion without result"
				)
			return res

	def close(self) -> None:
		"""Stop event listener thread and clear callbacks."""
		self._running = False


if not hasattr(WorkerClient, "send_command"):
	def _abstract_send_command(
		self: WorkerClient,
		cmd: dict[str, Any],
		timeout: float = 10.0,
	) -> dict[str, Any]:
		"""Send a JSON command frame over the command pipe, read the single JSON response frame, and return it."""
		raise NotImplementedError

	WorkerClient.send_command = _abstract_send_command  # type: ignore[attr-defined]


class NamedPipeWorkerClient(WorkerClient):
	"""WorkerClient implementation over Named Pipe endpoints."""

	def __init__(
		self,
		cmd_pipe_name: str = r"\\.\pipe\nvda_ai_worker_cmd",
		evt_pipe_name: str = r"\\.\pipe\nvda_ai_worker_evt",
		connect_timeout_seconds: float = 5.0,
		cmd_client: NamedPipeClient | None = None,
		evt_client: NamedPipeClient | None = None,
		handshake_response: HandshakeResponse | None = None,
		cmd_lock: threading.Lock | None = None,
	) -> None:
		self.cmd_pipe_name = cmd_pipe_name
		self.evt_pipe_name = evt_pipe_name
		self.connect_timeout_seconds = connect_timeout_seconds

		self._cmd_client = cmd_client if cmd_client is not None else NamedPipeClient(self.cmd_pipe_name)
		self._evt_client = evt_client if evt_client is not None else NamedPipeClient(self.evt_pipe_name)
		self._cmd_lock = cmd_lock if cmd_lock is not None else threading.Lock()
		self._job_client: NamedPipeJobClient | None = None
		self._handshake_response: HandshakeResponse | None = handshake_response
		self._needs_cmd_reconnect = False
		if handshake_response is not None and handshake_response.accepted:
			self._job_client = NamedPipeJobClient(
				self._cmd_client,
				self._evt_client,
				self._cmd_lock,
			)

	@property
	def cmd_lock(self) -> threading.Lock:
		"""Return the shared lock synchronizing command pipe RPC transactions."""
		return self._cmd_lock

	def connect(self) -> HandshakeResponse:
		"""Connect to worker named pipes and exchange versioned handshake."""
		self._cmd_client.connect(timeout_seconds=self.connect_timeout_seconds)
		self._evt_client.connect(timeout_seconds=self.connect_timeout_seconds)

		req = HandshakeRequest(
			protocol_version=PROTOCOL_VERSION,
			client_name="nvda_ai_assistant",
			client_version="1.0.0",
			client_pid=os.getpid(),
		)

		with self._cmd_lock:
			self._cmd_client.write_frame(req.to_dict())
			raw_resp = self._cmd_client.read_frame()

		self._handshake_response = HandshakeResponse.from_dict(raw_resp)
		if not self._handshake_response.accepted:
			self.disconnect()
			raise ValueError(
				f"Worker handshake rejected: {self._handshake_response.error_message}"
			)

		self._job_client = NamedPipeJobClient(
			self._cmd_client,
			self._evt_client,
			self._cmd_lock,
		)
		return self._handshake_response

	def disconnect(self) -> None:
		"""Gracefully disconnect pipe clients."""
		self._needs_cmd_reconnect = False
		if self._job_client:
			self._job_client.close()
			self._job_client = None

		for client in (self._evt_client, self._cmd_client):
			if client and getattr(client, "_handle", None):
				try:
					import ctypes
					ctypes.windll.kernel32.CancelIoEx(int(client._handle), None)
				except Exception:
					pass

		self._cmd_client.close()
		self._evt_client.close()
		self._handshake_response = None

	def is_connected(self) -> bool:
		"""Return True if both command and event pipes are connected."""
		return (
			(self._cmd_client.is_connected or self._needs_cmd_reconnect)
			and self._evt_client.is_connected
			and self._handshake_response is not None
			and self._handshake_response.accepted
		)

	def _reconnect_cmd(self, timeout: float = 5.0) -> None:
		"""Reconnect command pipe client after a stream desynchronization timeout."""
		if self._cmd_client:
			try:
				self._cmd_client.close()
			except Exception:
				pass
		self._cmd_client = NamedPipeClient(self.cmd_pipe_name)
		self._cmd_client.connect(timeout_seconds=timeout)
		if self._job_client:
			self._job_client._cmd_client = self._cmd_client
		self._needs_cmd_reconnect = False

	def poll_health(self) -> WorkerHealth:
		"""Request worker health snapshot."""
		with self._cmd_lock:
			if self._needs_cmd_reconnect:
				self._reconnect_cmd(timeout=5.0)
			self._cmd_client.write_frame({"type": "worker_health_ping"})
			resp = self._cmd_client.read_frame()

		return WorkerHealth.from_dict(resp)

	def send_command(
		self,
		cmd: dict[str, Any],
		timeout: float = 10.0,
	) -> dict[str, Any]:
		"""Send a JSON command frame over the command pipe, read the single JSON response frame, and return it."""
		deadline = time.monotonic() + timeout
		acquired = self._cmd_lock.acquire(timeout=max(0.0, timeout))
		if not acquired:
			raise TimeoutError(
				f"Timed out waiting for command lock after {timeout}s"
			)
		try:
			remaining = max(0.001, deadline - time.monotonic())
			if self._needs_cmd_reconnect:
				self._reconnect_cmd(timeout=remaining)
				remaining = max(0.001, deadline - time.monotonic())
			elif not self._cmd_client.is_connected:
				raise RuntimeError("WorkerClient command pipe is not connected")

			self._cmd_client.write_frame(cmd)
			try:
				return self._cmd_client.read_frame(timeout_seconds=remaining)
			except TypeError:
				return self._cmd_client.read_frame()
		except TimeoutError:
			try:
				import ctypes

				if getattr(self._cmd_client, "_handle", None):
					ctypes.windll.kernel32.CancelIoEx(
						int(self._cmd_client._handle), None
					)
			except Exception:
				pass
			try:
				self._cmd_client.close()
			except Exception:
				pass
			self._needs_cmd_reconnect = True
			raise
		finally:
			self._cmd_lock.release()

	def get_job_client(self) -> JobClient:
		"""Return active JobClient instance."""
		if not self._job_client:
			raise RuntimeError(
				"WorkerClient is not connected. Call connect() first."
			)
		return self._job_client

	# Duck-typed JobClient delegations for backwards compatibility
	def submit_job(self, spec: Any) -> str:
		return self.get_job_client().submit_job(spec)

	def cancel_job(self, job_id: str, reason: str = "user_cancelled") -> bool:
		return self.get_job_client().cancel_job(job_id, reason=reason)

	def get_job_snapshot(self, job_id: str) -> Any:
		return self.get_job_client().get_job_snapshot(job_id)

	def list_active_jobs(self) -> Any:
		return self.get_job_client().list_active_jobs()

	def wait_for_job(self, job_id: str, timeout_seconds: float | None = None) -> Any:
		return self.get_job_client().wait_for_job(job_id, timeout_seconds=timeout_seconds)

