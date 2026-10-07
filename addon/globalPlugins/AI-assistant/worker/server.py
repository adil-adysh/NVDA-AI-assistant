# -*- coding: utf-8 -*-
"""Worker Server and Execution Engine for Out-of-Process Task Execution.

Enforces Invariant A16 (pure-Python process isolation, zero NVDA imports),
Invariant A17 (versioned handshake negotiation v1.0.0),
Invariant A18 (NDJSON command and event pipe transport),
Invariant A19 (health telemetry and responsive lifecycle), and
Invariant A22 (two-phase cooperative cancellation at yield points).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import logging
import os
import queue
import sys
import threading
import time
from typing import Any

try:
	from ..core.job.cancellation import CancellationToken
	from ..core.job.dto import (
		HandshakeRequest,
		JobProgress,
		JobResult,
		JobSpec,
		JobStatus,
		WorkerHealth,
	)
	from ..core.job.protocol import (
		PROTOCOL_VERSION,
		validate_handshake,
	)
except (ImportError, ValueError):
	from core.job.cancellation import CancellationToken  # type: ignore[no-redef]
	from core.job.dto import (  # type: ignore[no-redef]
		HandshakeRequest,
		JobProgress,
		JobResult,
		JobSpec,
		JobStatus,
		WorkerHealth,
	)
	from core.job.protocol import (  # type: ignore[no-redef]
		PROTOCOL_VERSION,
		validate_handshake,
	)

from .ipc.security import build_user_only_security_attributes
from .ipc.transport import NamedPipeServer, PipeDisconnectedError
from .executors.model_download_job import (
	execute_model_download_job,
	execute_runtime_download_job,
)

logger = logging.getLogger(__name__)

DEFAULT_CMD_PIPE = r"\\.\pipe\nvda_ai_worker_cmd"
DEFAULT_EVT_PIPE = r"\\.\pipe\nvda_ai_worker_evt"


class WorkerServer:
	"""Multi-threaded out-of-process Worker IPC Server.

	Coordinates:
	- Command Pipe listener thread (RPC control plane).
	- Event Pipe broadcaster thread (streaming progress and results).
	- ThreadPoolExecutor for concurrent job execution.
	- Parent Process watchdog for clean self-termination.
	"""

	def __init__(
		self,
		cmd_pipe_name: str = DEFAULT_CMD_PIPE,
		evt_pipe_name: str = DEFAULT_EVT_PIPE,
		parent_pid: int = 0,
		max_workers: int | None = None,
	) -> None:
		self.cmd_pipe_name = cmd_pipe_name
		self.evt_pipe_name = evt_pipe_name
		self.parent_pid = parent_pid
		self.active_generation = 1
		self._start_time = time.time()
		self._running = False
		self._shutdown_event = threading.Event()

		# Security attributes
		self._security_attributes = build_user_only_security_attributes()

		# Pipe servers
		self._cmd_server: NamedPipeServer | None = None
		self._evt_server: NamedPipeServer | None = None

		# Concurrency & Registry
		workers = max_workers or min(4, max(1, os.cpu_count() or 1))
		self._executor = ThreadPoolExecutor(
			max_workers=workers, thread_name_prefix="worker_exec"
		)
		self._event_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1000)
		self._active_jobs: dict[str, CancellationToken] = {}
		self._registry_lock = threading.Lock()

		# Worker Threads
		self._cmd_thread: threading.Thread | None = None
		self._evt_thread: threading.Thread | None = None
		self._watchdog_thread: threading.Thread | None = None

	def start(self) -> None:
		"""Start command server, event broadcaster, and parent watchdog threads."""
		if self._running:
			return
		self._running = True
		self._shutdown_event.clear()

		self._cmd_server = NamedPipeServer(
			self.cmd_pipe_name, self._security_attributes
		)
		self._evt_server = NamedPipeServer(
			self.evt_pipe_name, self._security_attributes
		)

		self._cmd_thread = threading.Thread(
			target=self._run_cmd_listener,
			name="WorkerCmdListener",
			daemon=True,
		)
		self._cmd_thread.start()

		self._evt_thread = threading.Thread(
			target=self._run_evt_broadcaster,
			name="WorkerEvtBroadcaster",
			daemon=True,
		)
		self._evt_thread.start()

		if self.parent_pid > 0:
			self._watchdog_thread = threading.Thread(
				target=self._run_parent_watchdog,
				name="WorkerParentWatchdog",
				daemon=True,
			)
			self._watchdog_thread.start()

		logger.info(
			"WorkerServer started (PID=%d, parent_pid=%d)",
			os.getpid(),
			self.parent_pid,
		)

	def serve_forever(self) -> None:
		"""Block until server shutdown is requested."""
		self.start()
		try:
			while self._running and not self._shutdown_event.is_set():
				self._shutdown_event.wait(timeout=0.5)
		except KeyboardInterrupt:
			logger.info("WorkerServer interrupted")
		finally:
			self.shutdown()

	def shutdown(self) -> None:
		"""Signal shutdown, cancel active jobs, and close named pipe servers."""
		if not self._running:
			return
		self._running = False
		self._shutdown_event.set()

		# Cancel all in-flight jobs
		with self._registry_lock:
			for token in self._active_jobs.values():
				token.cancel()
			self._active_jobs.clear()

		# Shutdown executor
		self._executor.shutdown(wait=False, cancel_futures=True)

		# Close servers to unblock listening threads
		if self._cmd_server:
			self._cmd_server.close()
		if self._evt_server:
			self._evt_server.close()

		logger.info("WorkerServer shutdown complete")

	def _emit_event(self, event_data: dict[str, Any]) -> None:
		"""Queue an event for broadcasting over the Event Pipe."""
		try:
			self._event_queue.put_nowait(event_data)
		except queue.Full:
			logger.warning(
				"Event queue full; dropping event of type %s",
				event_data.get("type"),
			)

	def _run_evt_broadcaster(self) -> None:
		"""Event broadcasting loop: accepts event client and streams events."""
		while self._running and not self._shutdown_event.is_set():
			if not self._evt_server or self._evt_server.is_closed:
				break

			if not self._evt_server.is_connected:
				connected = self._evt_server.accept_connection(timeout_seconds=0.5)
				if not connected:
					continue

			try:
				event_dict = self._event_queue.get(timeout=0.2)
				self._evt_server.write_frame(event_dict)
				self._event_queue.task_done()
			except queue.Empty:
				continue
			except PipeDisconnectedError:
				logger.debug("Event pipe disconnected; waiting for reconnect")
				if self._evt_server:
					self._evt_server.disconnect()
			except Exception as exc:
				logger.error("Error in event broadcaster: %s", exc)

	def _run_cmd_listener(self) -> None:
		"""Command RPC loop: accepts client connection and dispatches requests."""
		while self._running and not self._shutdown_event.is_set():
			if not self._cmd_server or self._cmd_server.is_closed:
				break

			if not self._cmd_server.is_connected:
				connected = self._cmd_server.accept_connection(timeout_seconds=0.5)
				if not connected:
					continue

			try:
				frame = self._cmd_server.read_frame()
				self._handle_command(frame)
			except PipeDisconnectedError:
				logger.debug("Command pipe disconnected; waiting for reconnect")
				if self._cmd_server:
					self._cmd_server.disconnect()
			except Exception as exc:
				logger.error("Error reading command frame: %s", exc)

	def _handle_command(self, frame: dict[str, Any]) -> None:
		"""Process an incoming command frame and write response."""
		if not self._cmd_server or not self._cmd_server.is_connected:
			return

		cmd_type = str(frame.get("type", ""))

		if cmd_type == "handshake_request":
			req = HandshakeRequest.from_dict(frame)
			resp = validate_handshake(
				req,
				worker_version=PROTOCOL_VERSION,
				supported_capabilities=(
					"job.echo",
					"job.trivial_compute",
					"job.model_download",
					"job.runtime_download",
					"job.inference",
					"session.ocr",
					"session.transcription",
				),
				worker_pid=os.getpid(),
			)
			self._cmd_server.write_frame(resp.to_dict())

		elif cmd_type in ("worker_health_ping", "ping"):
			health = self._collect_health()
			self._cmd_server.write_frame(health.to_dict())

		elif cmd_type in ("job_cancellation_request", "cancel_job"):
			job_id = str(frame.get("job_id", ""))
			with self._registry_lock:
				token = self._active_jobs.get(job_id)
				if token:
					token.cancel()
					accepted = True
				else:
					accepted = False
			self._cmd_server.write_frame(
				{
					"type": "cancellation_ack",
					"job_id": job_id,
					"accepted": accepted,
				}
			)

		elif cmd_type in ("shutdown_command", "shutdown"):
			self._cmd_server.write_frame({"type": "shutdown_ack", "accepted": True})
			threading.Thread(target=self.shutdown, daemon=True).start()

		elif cmd_type in ("job_submission", "submit_job"):
			spec = JobSpec.from_dict(frame)
			token = CancellationToken(spec.job_id)
			with self._registry_lock:
				self._active_jobs[spec.job_id] = token

			# Send synchronous submission ack
			self._cmd_server.write_frame(
				{
					"type": "job_ack",
					"job_id": spec.job_id,
					"status": "accepted",
					"generation": self.active_generation,
				}
			)

			# Dispatch execution to thread pool
			self._executor.submit(self._dispatch_job, spec, token)

		else:
			self._cmd_server.write_frame(
				{
					"type": "error",
					"error_code": "UNKNOWN_COMMAND",
					"error_message": f"Unknown command type '{cmd_type}'",
				}
			)

	def _dispatch_job(self, spec: JobSpec, token: CancellationToken) -> None:
		"""Execute job asynchronously on thread pool."""
		try:
			if spec.job_type == "echo":
				self._execute_echo(spec, token)
			elif spec.job_type == "trivial_compute":
				self._execute_trivial_compute(spec, token)
			elif spec.job_type == "model_download":
				res = execute_model_download_job(
					spec, token, lambda p: self._emit_event(p.to_dict())
				)
				self._emit_event(res.to_dict())
			elif spec.job_type == "runtime_download":
				res = execute_runtime_download_job(
					spec, token, lambda p: self._emit_event(p.to_dict())
				)
				self._emit_event(res.to_dict())
			else:
				res = JobResult(
					job_id=spec.job_id,
					status=JobStatus.FAILED,
					error_code="UNSUPPORTED_JOB_TYPE",
					error_message=f"Job type '{spec.job_type}' not supported by worker",
					generation=spec.generation,
				)
				self._emit_event(res.to_dict())
		except Exception as exc:
			logger.exception("Unexpected error executing job %s: %s", spec.job_id, exc)
			res = JobResult(
				job_id=spec.job_id,
				status=JobStatus.FAILED,
				error_code="EXECUTION_ERROR",
				error_message=str(exc),
				generation=spec.generation,
			)
			self._emit_event(res.to_dict())
		finally:
			with self._registry_lock:
				self._active_jobs.pop(spec.job_id, None)

	def _execute_echo(self, spec: JobSpec, token: CancellationToken) -> None:
		"""Execute built-in echo job."""
		msg = spec.payload.get("message", "")
		# Stream brief progress
		self._emit_event(
			JobProgress(
				job_id=spec.job_id,
				status=JobStatus.RUNNING,
				progress_pct=50.0,
				status_message="Processing echo",
				generation=spec.generation,
			).to_dict()
		)

		res = JobResult(
			job_id=spec.job_id,
			status=JobStatus.COMPLETED,
			result_data={"echo": msg},
			duration_ms=1,
			generation=spec.generation,
		)
		self._emit_event(res.to_dict())

	def _execute_trivial_compute(
		self, spec: JobSpec, token: CancellationToken
	) -> None:
		"""Execute built-in multi-step compute job with yield-point cancellation."""
		steps = int(spec.payload.get("steps", 4))
		step_delay = float(spec.payload.get("step_delay", 0.02))

		t0 = time.perf_counter()
		for step in range(1, steps + 1):
			if token.is_cancelled:
				res = JobResult(
					job_id=spec.job_id,
					status=JobStatus.CANCELLED,
					result_data={"cancelled_at_step": step, "total_steps": steps},
					duration_ms=int((time.perf_counter() - t0) * 1000),
					generation=spec.generation,
				)
				self._emit_event(res.to_dict())
				return

			time.sleep(step_delay)
			pct = round((step / steps) * 100.0, 2)
			update = JobProgress(
				job_id=spec.job_id,
				status=JobStatus.RUNNING,
				progress_pct=pct,
				status_message=f"Step {step}/{steps} completed",
				generation=spec.generation,
			)
			self._emit_event(update.to_dict())

		res = JobResult(
			job_id=spec.job_id,
			status=JobStatus.COMPLETED,
			result_data={"steps_completed": steps, "output": "compute_ok"},
			duration_ms=int((time.perf_counter() - t0) * 1000),
			generation=spec.generation,
		)
		self._emit_event(res.to_dict())

	def _collect_health(self) -> WorkerHealth:
		"""Capture point-in-time worker health and resource metrics."""
		uptime = time.time() - self._start_time
		with self._registry_lock:
			active_jobs_count = len(self._active_jobs)

		rss_bytes = 0
		if sys.platform == "win32":
			try:
				import win32process

				info = win32process.GetProcessMemoryInfo(
					win32process.GetCurrentProcess()
				)
				rss_bytes = int(info.get("WorkingSetSize", 0))
			except Exception:
				pass

		return WorkerHealth(
			worker_pid=os.getpid(),
			generation=self.active_generation,
			uptime_seconds=uptime,
			active_jobs_count=active_jobs_count,
			active_sessions_count=0,
			cpu_percent=0.0,
			rss_memory_bytes=rss_bytes,
			gpu_available=False,
			is_healthy=True,
		)

	def _run_parent_watchdog(self) -> None:
		"""Monitors parent process existence; triggers shutdown if parent disappears."""
		while self._running and not self._shutdown_event.is_set():
			time.sleep(0.5)
			if not self._is_process_alive(self.parent_pid):
				logger.warning(
					"Parent process PID %d no longer alive; terminating worker",
					self.parent_pid,
				)
				self.shutdown()
				break

	def _is_process_alive(self, pid: int) -> bool:
		"""Check if process with given PID exists."""
		if pid <= 0:
			return True
		if sys.platform == "win32":
			try:
				import win32process

				# OpenProcess with PROCESS_QUERY_LIMITED_INFORMATION (0x1000)
				handle = win32process.OpenProcess(0x1000, False, pid)
				exit_code = win32process.GetExitCodeProcess(handle)
				# STILL_ACTIVE = 259
				return exit_code == 259
			except Exception:
				return False
		else:
			try:
				os.kill(pid, 0)
				return True
			except OSError:
				return False
