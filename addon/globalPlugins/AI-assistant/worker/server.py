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
from dataclasses import replace
import os
import queue
import sys
import threading
import time
from typing import Any

try:
	from ..core.job.cancellation import CancellationToken
	from ..core.job.cancellation import JobCancelledError
	from ..core.job.execution import job_execution_scope
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
	from core.job.cancellation import JobCancelledError
	from core.job.execution import job_execution_scope
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

from .runtime_commands import execute_runtime_command
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
		litert_executor: Any | None = None,
		llama_executor: Any | None = None,
	) -> None:
		self.cmd_pipe_name = cmd_pipe_name
		self.evt_pipe_name = evt_pipe_name
		self.parent_pid = parent_pid
		self.active_generation = 1
		self._start_time = time.time()
		self._running = False
		self._shutdown_event = threading.Event()
		self._litert_executor = litert_executor
		self._llama_executor = llama_executor

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
		self._event_queue: queue.Queue[dict[str, Any]] = queue.Queue()
		self._active_jobs: dict[str, CancellationToken] = {}
		self._control_jobs: set[str] = set()
		self._registry_lock = threading.Lock()
		self._runtime_locks = {"litert": threading.Lock(), "llama": threading.Lock()}
		self._control_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="worker_control")
		self._executor_lock = threading.Lock()
		self._execution_lanes = {name: ThreadPoolExecutor(max_workers=1, thread_name_prefix="worker_" + name)
			for name in ("litert", "llama", "embedding", "conversation")}

		# Worker Threads
		self._cmd_thread: threading.Thread | None = None
		self._evt_thread: threading.Thread | None = None
		self._watchdog_thread: threading.Thread | None = None

	def get_litert_executor(self) -> Any:
		"""Return the LiteRT host executor, initializing if necessary."""
		with self._executor_lock:
			if self._litert_executor is None:
				try:
					from .executors.litert import LiteRTWorkerExecutor
				except (ImportError, ValueError):
					from worker.executors.litert import LiteRTWorkerExecutor  # type: ignore[no-redef]
				self._litert_executor = LiteRTWorkerExecutor()
			return self._litert_executor

	def get_model_asset_executor(self) -> Any:
		with self._executor_lock:
			if not hasattr(self, "_model_asset_executor"):
				try:
					from .executors.model_assets import ModelAssetExecutor, default_cache_roots
				except ImportError:
					from worker.executors.model_assets import ModelAssetExecutor, default_cache_roots
				self._model_asset_executor = ModelAssetExecutor()
				self._default_cache_roots = default_cache_roots
			return self._model_asset_executor

	def get_llama_executor(self) -> Any:
		"""Return the llama.cpp host executor, initializing if necessary."""
		with self._executor_lock:
			if self._llama_executor is None:
				try:
					from .executors.llama import LlamaWorkerExecutor
				except (ImportError, ValueError):
					from worker.executors.llama import LlamaWorkerExecutor  # type: ignore[no-redef]
				self._llama_executor = LlamaWorkerExecutor()
			return self._llama_executor

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
			tokens = tuple(self._active_jobs.values())
		for token in tokens:
			token.cancel("shutdown")

		# Shutdown executor
		self._executor.shutdown(wait=False, cancel_futures=True)
		self._control_executor.shutdown(wait=False, cancel_futures=True)
		for lane in self._execution_lanes.values():
			lane.shutdown(wait=False, cancel_futures=True)

		# Close servers to unblock listening threads
		if self._cmd_server:
			self._cmd_server.close()
		if self._evt_server:
			self._evt_server.close()

		logger.info("WorkerServer shutdown complete")

	def _emit_event(self, event_data: dict[str, Any]) -> None:
		"""Queue an event for broadcasting over the Event Pipe."""
		try:
			if event_data.get("type") == "job_update" and self._event_queue.qsize() >= 1000:
				return
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
				self._event_queue.put_nowait(event_dict)
				self._event_queue.task_done()
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

		cmd_type = str(frame.get("type", "") or frame.get("command", ""))

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
					"job.runtime_command",
					"job.embedding",
					"job.conversation",
					"job.inference",
					"session.ocr",
					"session.transcription",
					"runtime.litert",
					"runtime.llama",
				),
				worker_pid=os.getpid(),
			)
			self._cmd_server.write_frame(replace(resp, generation=self.active_generation).to_dict())

		elif cmd_type in ("worker_health_ping", "ping"):
			health = self._collect_health()
			self._cmd_server.write_frame(health.to_dict())

		elif cmd_type in ("job_cancellation_request", "cancel_job"):
			job_id = str(frame.get("job_id", ""))
			with self._registry_lock:
				token = self._active_jobs.get(job_id)
				accepted = token is not None
			if token is not None:
				token.cancel()
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
			command = str(spec.payload.get("type", ""))
			control = spec.job_type == "runtime_command" and command.endswith(("_stop", "_get_status", "_status"))
			with self._registry_lock:
				full = (len(self._control_jobs) >= 8 or self._event_queue.qsize() >= 1128) if control else (
					len(self._active_jobs) - len(self._control_jobs) >= 128 or self._event_queue.qsize() >= 1000)
				if spec.job_id in self._active_jobs or full:
					self._cmd_server.write_frame({"type": "job_ack", "status": "rejected",
						"error_message": "Duplicate job ID or worker queue is full", "job_id": spec.job_id})
					return
				self._active_jobs[spec.job_id] = token
				if control:
					self._control_jobs.add(spec.job_id)

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
			command = str(spec.payload.get("type", ""))
			if spec.job_type == "runtime_command":
				if command.endswith(("_stop", "_get_status", "_status")):
					pool = self._control_executor
				else:
					pool = self._execution_lanes.get(command.split("_", 1)[0], self._executor)
			else:
				pool = self._execution_lanes.get(spec.job_type, self._executor)
			pool.submit(self._dispatch_job, spec, token)

		else:
			# Legacy command support for older clients; current clients submit jobs.
			execute_runtime_command(self, frame, self._cmd_server.write_frame)

	def _dispatch_job(self, spec: JobSpec, token: CancellationToken) -> None:
		"""Execute job asynchronously on thread pool."""
		try:
			if spec.job_type == "runtime_command":
				self._execute_runtime_job(spec, token)
			elif spec.job_type == "conversation":
				from .executors.conversation import execute_conversation_job
				self._emit_event(execute_conversation_job(spec, token).to_dict())
			elif spec.job_type == "embedding":
				from .executors.embedding import execute_embedding_job
				self._emit_event(execute_embedding_job(spec, token).to_dict())
			elif spec.job_type == "echo":
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
		except JobCancelledError:
			self._emit_event(JobResult(job_id=spec.job_id, status=JobStatus.CANCELLED,
				generation=spec.generation).to_dict())
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
				self._control_jobs.discard(spec.job_id)

	def _execute_runtime_job(self, spec, token):
		command = str(spec.payload.get("type", ""))
		family = command.split("_", 1)[0]
		try:
			from ..core.job.operations import RUNTIME_COMMANDS
		except ImportError:
			from core.job.operations import RUNTIME_COMMANDS
		if command not in RUNTIME_COMMANDS:
			raise ValueError("Unsupported runtime command")
		response = {}
		def write(frame):
			if frame.get("type") == "runtime_progress":
				self._emit_event(JobProgress(job_id=spec.job_id, status=JobStatus.RUNNING,
					status_message=str(frame.get("stage", "")), generation=spec.generation).to_dict())
			else:
				response.update(frame)
		lock = None if command.endswith(("_stop", "_get_status", "_status")) else self._runtime_locks[family]
		acquired = False
		finished = threading.Event()
		watcher = None
		try:
			if lock is not None:
				while not lock.acquire(timeout=0.05):
					token.check_cancelled()
				acquired = True
			token.check_cancelled()
			if command.endswith(("_ensure_ready", "_restart")):
				executor = self.get_litert_executor() if family == "litert" else self.get_llama_executor()
				before = executor.get_status()
				def cancel_owned_startup():
					status = executor.get_status()
					owned = not status.get("is_adopted") and (status.get("is_running") or status.get("state") in ("starting", "restarting"))
					changed = status.get("generation") != before.get("generation") or not before.get("is_running") or command.endswith("_restart")
					if owned and changed:
						try:
							executor.stop(timeout_seconds=2.0)
						except Exception:
							logger.exception("Could not stop cancelled startup")
				def cancel_startup():
					while not finished.wait(0.05):
						if token.is_cancelled:
							cancel_owned_startup()

				watcher = threading.Thread(target=cancel_startup, name="WorkerStartupCancellation", daemon=True)
				watcher.start()
			with job_execution_scope(token):
				execute_runtime_command(self, spec.payload, write)
			token.check_cancelled()
		finally:
			if watcher is not None and token.is_cancelled:
				cancel_owned_startup()
			finished.set()
			if watcher is not None:
				watcher.join(timeout=3.0)
			if acquired:
				lock.release()
		status = JobStatus.COMPLETED if response.get("success", False) else JobStatus.FAILED
		self._emit_event(JobResult(job_id=spec.job_id, status=status, result_data=response,
			error_code=response.get("error_code"), error_message=response.get("error_message"),
			generation=spec.generation).to_dict())

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
				import win32api
				import win32process

				# OpenProcess with PROCESS_QUERY_LIMITED_INFORMATION (0x1000)
				handle = win32api.OpenProcess(0x1000, False, pid)
				try:
					exit_code = win32process.GetExitCodeProcess(handle)
				finally:
					handle.Close()
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
