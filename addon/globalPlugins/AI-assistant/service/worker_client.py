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
import queue
from uuid import uuid4
from dataclasses import replace
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
		command_sender=None,
		generation: int = 1,
	) -> None:
		self._cmd_client = cmd_client
		self._evt_client = evt_client
		self._cmd_lock = cmd_lock or threading.Lock()
		self._command_sender = command_sender
		self.generation = generation

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
					self._fail_pending_jobs()
					break
				frame = self._evt_client.read_frame()
				self._handle_event_frame(frame)
			except PipeDisconnectedError:
				logger.debug("Event pipe disconnected in JobClient")
				self._fail_pending_jobs()
				break
			except Exception as exc:
				if not self._running:
					break
				logger.error("Error in JobClient event listener: %s", exc)

	def _fail_pending_jobs(self) -> None:
		"""Release waiters and notify subscribers exactly once when transport dies."""
		from ..core.translation import _
		callbacks = []
		with self._lock:
			self._running = False
			for job_id, snapshot in self._snapshots.items():
				if snapshot.state.is_terminal or job_id in self._results:
					continue
				result = JobResult(
					job_id=job_id, status=JobStatus.FAILED,
					error_code="WORKER_DISCONNECTED",
					error_message=_("The local AI worker disconnected. Please try again."),
					retriable=True, generation=snapshot.spec.generation,
				)
				self._results[job_id] = result
				self._snapshots[job_id] = JobSnapshot(
					spec=snapshot.spec, state=result.status, progress=snapshot.progress,
					result=result, created_at_epoch_ms=snapshot.created_at_epoch_ms,
					updated_at_epoch_ms=int(time.time() * 1000),
				)
				self._result_events[job_id].set()
				callbacks.extend((callback, result) for callback in self._result_callbacks.get(job_id, []))
		for callback, result in callbacks:
			try:
				callback(result)
			except Exception:
				logger.exception("Error reporting disconnected worker job")

	def _handle_event_frame(self, frame: dict[str, Any]) -> None:
		"""Process an incoming event frame (JobUpdate or JobResult)."""
		frame_type = str(frame.get("type", ""))

		if frame_type == "job_update":
			progress = JobProgress.from_dict(frame)
			job_id = progress.job_id
			with self._lock:
				snap = self._snapshots.get(job_id)
				if snap is None or progress.generation != snap.spec.generation or snap.state.is_terminal:
					return
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
				snapshot = self._snapshots.get(job_id)
				if job_id in self._results or snapshot is None or result.generation != snapshot.spec.generation:
					return
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
		spec = replace(spec, generation=self.generation)
		with self._lock:
			if not self._running:
				raise RuntimeError("Local AI worker is disconnected")
			if spec.job_id in self._snapshots:
				raise ValueError("Duplicate job ID")
			self._snapshots[spec.job_id] = JobSnapshot(
				spec=spec,
				state=JobStatus.SUBMITTED,
				created_at_epoch_ms=int(time.time() * 1000),
				updated_at_epoch_ms=int(time.time() * 1000),
			)
			self._result_events[spec.job_id] = threading.Event()

		try:
			ack = self._control_transaction(spec.to_dict())
		except Exception:
			self.forget_job(spec.job_id)
			raise

		if ack.get("type") != "job_ack" or ack.get("status") != "accepted":
			err_msg = ack.get("error_message", "Job submission rejected")
			self.forget_job(spec.job_id)
			raise RuntimeError(f"Submission failed for {spec.job_id}: {err_msg}")

		with self._lock:
			snap = self._snapshots.get(spec.job_id)
			if snap and snap.state == JobStatus.SUBMITTED:
				self._snapshots[spec.job_id] = JobSnapshot(
					spec=snap.spec,
					state=JobStatus.QUEUED,
					created_at_epoch_ms=snap.created_at_epoch_ms,
					updated_at_epoch_ms=int(time.time() * 1000),
				)

		return spec.job_id

	def _control_transaction(self, frame, timeout=5.0):
		if self._command_sender is not None:
			return self._command_sender(frame, timeout=timeout)
		deadline = time.monotonic() + timeout
		if not self._cmd_lock.acquire(timeout=timeout):
			raise TimeoutError("Worker control channel is busy")
		try:
			self._cmd_client.write_frame(frame)
			return self._cmd_client.read_frame(timeout_seconds=max(0.001, deadline - time.monotonic()))
		finally:
			self._cmd_lock.release()

	def cancel_job(self, job_id: str, reason: str = "user_cancelled") -> bool:
		ack = self._control_transaction({"type": "job_cancellation_request",
			"job_id": job_id, "reason": reason})
		return bool(ack.get("accepted", False))

	def forget_job(self, job_id):
		"""Release completed/abandoned job state; late events are ignored."""
		with self._lock:
			for mapping in (self._snapshots, self._results, self._result_events,
				self._progress_callbacks, self._result_callbacks):
				mapping.pop(job_id, None)

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
		self._fail_pending_jobs()


if not hasattr(WorkerClient, "send_command"):
	def _abstract_send_command(
		self: WorkerClient,
		cmd: dict[str, Any],
		timeout: float = 10.0,
	) -> dict[str, Any]:
		"""Consume optional readiness stages followed by the final RPC response.

		The command lock remains held for the complete transaction. Callback
		failures must not leave the final response unread for the next RPC.
		"""
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
		self._runtime_status_lock = threading.Lock()
		self._runtime_statuses = {}
		self._runtime_status_refreshing = set()
		self._runtime_status_times = {}
		if handshake_response is not None and handshake_response.accepted:
			self._job_client = NamedPipeJobClient(
				self._cmd_client,
				self._evt_client,
				self._cmd_lock, command_sender=self._send_control_command,
				generation=handshake_response.generation,
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
			self._cmd_lock, command_sender=self._send_control_command,
			generation=self._handshake_response.generation,
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
		return WorkerHealth.from_dict(self._send_control_command({"type": "worker_health_ping"}, timeout=5.0))

	def get_runtime_status_snapshot(self, runtime):
		"""Never block the NVDA event thread; refresh through a control job."""
		with self._runtime_status_lock:
			snapshot = self._runtime_statuses.get(runtime)
			refresh = runtime not in self._runtime_status_refreshing and time.monotonic() - self._runtime_status_times.get(runtime, 0) > 0.5
			if refresh:
				self._runtime_status_refreshing.add(runtime)
		if refresh:
			def update():
				try:
					self.send_command({"type": runtime + "_get_status"}, timeout=5.0)
				except Exception:
					logger.debug("Passive runtime status refresh failed", exc_info=True)
				finally:
					with self._runtime_status_lock:
						self._runtime_status_refreshing.discard(runtime)
						self._runtime_status_times[runtime] = time.monotonic()
			threading.Thread(target=update, name="WorkerStatusRefresh", daemon=True).start()
		return dict(snapshot) if snapshot else None

	def send_command(self, cmd, timeout=10.0, on_progress=None):
		command = str(cmd.get("type", "") or cmd.get("command", ""))
		capabilities = self._handshake_response.negotiated_capabilities if self._handshake_response else ()
		from ..core.job.operations import RUNTIME_COMMANDS
		if command in RUNTIME_COMMANDS and "job.runtime_command" in capabilities:
			response = self.run_job("runtime_command", cmd, timeout=timeout, on_progress=on_progress)
		else:
			response = self._send_control_command(cmd, timeout=timeout, on_progress=on_progress)
		status = response.get("status")
		if isinstance(status, dict) and command in RUNTIME_COMMANDS:
			with self._runtime_status_lock:
				self._runtime_statuses[command.split("_", 1)[0]] = dict(status)
		return response

	def run_job(self, job_type, payload, *, timeout=300.0, on_progress=None, cancel_event=None):
		"""Wait off the NVDA thread; release the control channel immediately after ack."""
		from ..core.cancellation import current_cancellation_token, RequestCancelled
		from ..core.readiness_progress import render_readiness_stage
		request_token = current_cancellation_token()
		jobs = self.get_job_client()
		job_id = str(uuid4())
		progress = queue.SimpleQueue()
		unsubscribe = jobs.subscribe_progress(job_id, progress.put)
		deadline = time.monotonic() + timeout
		try:
			if (request_token and request_token.cancelled) or (cancel_event and cancel_event.is_set()):
				raise RequestCancelled()
			jobs.submit_job(JobSpec(job_id=job_id, job_type=job_type, payload=payload,
				timeout_seconds=timeout, generation=jobs.generation))
			while True:
				cancelled = (request_token and request_token.cancelled) or (cancel_event and cancel_event.is_set())
				if cancelled:
					jobs.cancel_job(job_id)
					raise RequestCancelled(request_token.partial_text if request_token else "")
				remaining = deadline - time.monotonic()
				if remaining <= 0:
					jobs.cancel_job(job_id, reason="deadline_exceeded")
					raise TimeoutError("Timed out waiting for worker job")
				while not progress.empty():
					update = progress.get()
					message = render_readiness_stage(update.status_message) if job_type == "runtime_command" else update.status_message
					if message and on_progress:
						try:
							on_progress(message)
						except Exception:
							logger.exception("Worker progress callback failed")
				try:
					result = jobs.wait_for_job(job_id, timeout_seconds=min(0.05, remaining))
				except TimeoutError:
					continue
				if result.status == JobStatus.CANCELLED:
					raise RequestCancelled()
				if result.status == JobStatus.FAILED:
					return {**result.result_data, "type": "error", "success": False,
						"error_code": result.error_code, "error_message": result.error_message}
				return result.result_data
		finally:
			unsubscribe()
			jobs.forget_job(job_id)

	def _send_control_command(
		self,
		cmd: dict[str, Any],
		timeout: float = 10.0,
		on_progress: Callable[[str], None] | None = None,
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

			try:
				self._cmd_client.write_frame(cmd, timeout_seconds=max(0.001, deadline - time.monotonic()))
			except TypeError:
				# Legacy injected transports in tests do not implement write deadlines.
				self._cmd_client.write_frame(cmd)
			while True:
				remaining = deadline - time.monotonic()
				if remaining <= 0:
					raise TimeoutError("Timed out waiting for worker response")
				try:
					response = self._cmd_client.read_frame(timeout_seconds=remaining)
				except TypeError:
					response = self._cmd_client.read_frame()
				if response.get("type") != "runtime_progress":
					return response
				if on_progress is not None:
					from ..core.readiness_progress import render_readiness_stage
					message = render_readiness_stage(str(response.get("stage", "")))
					if message:
						try:
							on_progress(message)
						except Exception:
							logger.exception("Readiness progress callback failed")
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

