# -*- coding: utf-8 -*-
"""Worker Lifecycle Supervisor with Windows Job Object Containment & Circuit Breaker.

Enforces Invariant A16 (Windows Job Object containment),
Invariant A17 (semantic handshake v1.0.0 negotiation),
Invariant A19 (monotonic 5.0s heartbeat, 15.0s liveness timeout, fast broken-pipe detection),
Invariant A20 (generation fencing, exponential backoff, circuit breaker tripping), and
Invariant A26 (kernel-level child containment).
"""

from __future__ import annotations

from collections import deque
from enum import StrEnum
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any, Callable

try:
	from ..core.job.client import WorkerClient
	from ..core.job.dto import (
		HandshakeRequest,
		HandshakeResponse,
		WorkerHealth,
	)
	from ..core.job.protocol import PROTOCOL_VERSION
	from ..worker.ipc.transport import NamedPipeClient, PipeDisconnectedError
	from ..worker.job_object import JobObject, create_worker_job_object
except (ImportError, ValueError):
	from core.job.client import WorkerClient  # type: ignore[no-redef]
	from core.job.dto import (  # type: ignore[no-redef]
		HandshakeRequest,
		HandshakeResponse,
		WorkerHealth,
	)
	from core.job.protocol import PROTOCOL_VERSION  # type: ignore[no-redef]
	from worker.ipc.transport import (  # type: ignore[no-redef]
		NamedPipeClient,
		PipeDisconnectedError,
	)
	from worker.job_object import (  # type: ignore[no-redef]
		JobObject,
		create_worker_job_object,
	)


logger = logging.getLogger(__name__)


class SupervisorState(StrEnum):
	"""Discrete lifecycle states of the Worker Supervisor."""

	STOPPED = "stopped"
	STARTING = "starting"
	HANDSHAKING = "handshaking"
	RUNNING = "running"
	CRASHED = "crashed"
	RESTARTING = "restarting"
	FAILED_TRIPPED = "failed_tripped"


class StderrRingBuffer:
	"""Thread-safe bounded ring buffer retaining the last 64 KB of worker stderr (RS-08)."""

	def __init__(self, max_bytes: int = 65536) -> None:
		self.max_bytes = max_bytes
		self._buffer = bytearray()
		self._lock = threading.Lock()

	def append(self, data: bytes) -> None:
		with self._lock:
			self._buffer.extend(data)
			if len(self._buffer) > self.max_bytes:
				del self._buffer[: len(self._buffer) - self.max_bytes]

	def get_text(self) -> str:
		with self._lock:
			return self._buffer.decode("utf-8", errors="replace")

	def clear(self) -> None:
		with self._lock:
			self._buffer.clear()


class WorkerSupervisor:
	"""NVDA-side Worker Process Lifecycle Supervisor.

	Manages process launching enclosed in a Win32 Job Object, versioned handshake,
	monotonic heartbeat probes, diagnostic stderr capture, generation fencing,
	exponential backoff, and circuit breaker tripping after repeated crashes.
	"""

	def __init__(
		self,
		cmd_pipe_name: str = r"\\.\pipe\nvda_ai_worker_cmd",
		evt_pipe_name: str = r"\\.\pipe\nvda_ai_worker_evt",
		worker_script_path: str | Path | None = None,
		ping_interval_seconds: float = 5.0,
		liveness_timeout_seconds: float = 15.0,
		connect_timeout_seconds: float = 5.0,
		crash_window_seconds: float = 60.0,
		max_crashes_in_window: int = 3,
		base_backoff_seconds: float = 1.0,
		max_backoff_seconds: float = 10.0,
		auto_restart: bool = True,
		on_circuit_breaker_tripped: Callable[[str], None] | None = None,
	) -> None:
		self.cmd_pipe_name = cmd_pipe_name
		self.evt_pipe_name = evt_pipe_name
		self.ping_interval_seconds = ping_interval_seconds
		self.liveness_timeout_seconds = liveness_timeout_seconds
		self.connect_timeout_seconds = connect_timeout_seconds
		self.crash_window_seconds = crash_window_seconds
		self.max_crashes_in_window = max_crashes_in_window
		self.base_backoff_seconds = base_backoff_seconds
		self.max_backoff_seconds = max_backoff_seconds
		self.auto_restart = auto_restart
		self.on_circuit_breaker_tripped = on_circuit_breaker_tripped

		# Locate worker entrypoint
		if worker_script_path is None:
			candidate = (
				Path(__file__).resolve().parent.parent.parent.parent
				/ "ai_assistant_worker.py"
			)
			if not candidate.is_file():
				# Try repo root relative to current directory
				candidate = Path("ai_assistant_worker.py").resolve()
			self.worker_script_path = candidate
		else:
			self.worker_script_path = Path(worker_script_path).resolve()

		# State & Generation
		self.state = SupervisorState.STOPPED
		self.active_generation = 1
		self._restart_attempts = 0
		self._crash_timestamps: deque[float] = deque()
		self._last_pong_monotonic = 0.0
		self._latest_health: WorkerHealth | None = None

		# Handles & Threads
		self._process: subprocess.Popen[bytes] | None = None
		self._job_object: JobObject | None = None
		self._cmd_client: NamedPipeClient | None = None
		self._evt_client: NamedPipeClient | None = None
		self._worker_client: WorkerClient | None = None
		self.stderr_buffer = StderrRingBuffer(max_bytes=65536)

		self._cmd_lock = threading.Lock()
		self._state_lock = threading.Lock()
		self._shutdown_event = threading.Event()
		self._heartbeat_thread: threading.Thread | None = None
		self._stderr_thread: threading.Thread | None = None

	@property
	def is_running(self) -> bool:
		return self.state == SupervisorState.RUNNING

	@property
	def process_pid(self) -> int | None:
		return self._process.pid if self._process else None

	@property
	def latest_health(self) -> WorkerHealth | None:
		return self._latest_health

	def start(self, auto_connect_pipes: bool = True) -> bool:
		"""Start worker process, assign to Job Object, connect pipes, and handshake."""
		with self._state_lock:
			if self.state in (
				SupervisorState.RUNNING,
				SupervisorState.STARTING,
			):
				return True
			if self.state == SupervisorState.FAILED_TRIPPED:
				logger.warning(
					"Cannot start worker: Circuit breaker is TRIPPED. Reset required."
				)
				return False

			self.state = SupervisorState.STARTING
			self._shutdown_event.clear()

		try:
			self._spawn_worker_process()
			if auto_connect_pipes:
				self._connect_and_handshake()
			set_worker_supervisor(self)
			return True
		except Exception as exc:
			logger.error("Failed to start worker process: %s", exc)
			self._handle_crash(reason=f"STARTUP_ERROR: {exc}")
			return False

	def _spawn_worker_process(self) -> None:
		"""Spawn the worker process enclosed in Windows Job Object."""
		self._job_object = create_worker_job_object()

		cmd = [
			sys.executable,
			str(self.worker_script_path),
			"--cmd-pipe",
			self.cmd_pipe_name,
			"--evt-pipe",
			self.evt_pipe_name,
			"--parent-pid",
			str(os.getpid()),
			"--log-level",
			"DEBUG",
		]

		creationflags = 0
		startupinfo = None
		if sys.platform == "win32":
			creationflags = (
				subprocess.CREATE_NO_WINDOW
				| subprocess.CREATE_NEW_PROCESS_GROUP
			)
			startupinfo = subprocess.STARTUPINFO()
			startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
			startupinfo.wShowWindow = subprocess.SW_HIDE

		self.stderr_buffer.clear()
		self._process = subprocess.Popen(
			cmd,
			stdin=subprocess.DEVNULL,
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE,
			creationflags=creationflags,
			startupinfo=startupinfo,
		)

		# Assign to Job Object immediately
		if self._job_object and self._process:
			self._job_object.assign_process(self._process)
			logger.debug(
				"Worker process PID=%d assigned to JobObject", self._process.pid
			)

		# Drain stderr into ring buffer
		if self._process and self._process.stderr:
			self._stderr_thread = threading.Thread(
				target=self._drain_stderr,
				args=(self._process.stderr,),
				name="WorkerStderrDrain",
				daemon=True,
			)
			self._stderr_thread.start()

	def _drain_stderr(self, pipe: Any) -> None:
		"""Continuously read stderr bytes into bounded ring buffer."""
		try:
			while not self._shutdown_event.is_set():
				chunk = pipe.read(4096)
				if not chunk:
					break
				self.stderr_buffer.append(chunk)
		except Exception:
			pass

	def _connect_and_handshake(self) -> None:
		"""Establish named pipe connections and perform versioned handshake exchange."""
		with self._state_lock:
			self.state = SupervisorState.HANDSHAKING

		# Connect command pipe
		self._cmd_client = NamedPipeClient(self.cmd_pipe_name)
		self._cmd_client.connect(timeout_seconds=self.connect_timeout_seconds)

		# Connect event pipe
		self._evt_client = NamedPipeClient(self.evt_pipe_name)
		self._evt_client.connect(timeout_seconds=self.connect_timeout_seconds)

		# Handshake request
		req = HandshakeRequest(
			protocol_version=PROTOCOL_VERSION,
			client_name="nvda_ai_assistant",
			client_version="1.0.0",
			client_pid=os.getpid(),
		)

		with self._cmd_lock:
			self._cmd_client.write_frame(req.to_dict())
			raw_resp = self._cmd_client.read_frame()

		resp = HandshakeResponse.from_dict(raw_resp)
		if not resp.accepted:
			raise ValueError(f"Worker rejected handshake: {resp.error_message}")

		try:
			from ..service.worker_client import NamedPipeWorkerClient
		except (ImportError, ValueError):
			from service.worker_client import NamedPipeWorkerClient  # type: ignore[no-redef]
		self._worker_client = NamedPipeWorkerClient(
			cmd_pipe_name=self.cmd_pipe_name,
			evt_pipe_name=self.evt_pipe_name,
			cmd_client=self._cmd_client,
			evt_client=self._evt_client,
			handshake_response=resp,
			cmd_lock=self._cmd_lock,
		)

		with self._state_lock:
			self.state = SupervisorState.RUNNING
			self._last_pong_monotonic = time.monotonic()
			self._restart_attempts = 0  # reset backoff on successful handshake


		# Start heartbeat loop
		self._heartbeat_thread = threading.Thread(
			target=self._run_heartbeat_loop,
			name="WorkerHeartbeatWatchdog",
			daemon=True,
		)
		self._heartbeat_thread.start()
		logger.info(
			"Worker connected and handshaked successfully (PID=%d, generation=%d)",
			self.process_pid or 0,
			self.active_generation,
		)

	def _run_heartbeat_loop(self) -> None:
		"""Periodic monotonic heartbeat watchdog probing worker liveness."""
		while self.is_running and not self._shutdown_event.is_set():
			time.sleep(self.ping_interval_seconds)
			if not self.is_running or self._shutdown_event.is_set():
				break

			now = time.monotonic()
			# Check liveness timeout
			if (
				now - self._last_pong_monotonic
				> self.liveness_timeout_seconds
			):
				logger.error(
					"Worker liveness timeout exceeded (%.1fs > %.1fs); initiating recovery",
					now - self._last_pong_monotonic,
					self.liveness_timeout_seconds,
				)
				self._handle_crash(reason="LIVENESS_TIMEOUT")
				break

			# Send probe
			try:
				with self._cmd_lock:
					if not self._cmd_client or not self._cmd_client.is_connected:
						raise PipeDisconnectedError(
							"Command pipe is not connected"
						)
					self._cmd_client.write_frame(
						{
							"type": "worker_health_ping",
							"timestamp_epoch_ms": int(time.time() * 1000),
							"generation": self.active_generation,
						}
					)
					resp_frame = self._cmd_client.read_frame()

				# Discard if older generation
				frame_gen = int(
					resp_frame.get("generation", self.active_generation)
				)
				if frame_gen >= self.active_generation:
					self._last_pong_monotonic = time.monotonic()
					if resp_frame.get("type") == "worker_health":
						self._latest_health = WorkerHealth.from_dict(resp_frame)
			except Exception as exc:
				logger.warning("Heartbeat probe failed: %s", exc)
				self._handle_crash(reason=f"HEARTBEAT_PROBE_FAILED: {exc}")
				break

	def _handle_crash(self, reason: str = "WORKER_CRASHED") -> None:
		"""Handle worker crash, record circuit breaker failure, and restart if permitted."""
		with self._state_lock:
			if self.state in (
				SupervisorState.STOPPED,
				SupervisorState.FAILED_TRIPPED,
			):
				return
			self.state = SupervisorState.CRASHED

		logger.warning("Worker failure detected: %s", reason)

		# Capture exit diagnostics
		self._teardown_process_handles(force_kill=True)

		# Circuit breaker sliding window check
		now = time.monotonic()
		while (
			self._crash_timestamps
			and (now - self._crash_timestamps[0]) > self.crash_window_seconds
		):
			self._crash_timestamps.popleft()
		self._crash_timestamps.append(now)

		if len(self._crash_timestamps) >= self.max_crashes_in_window:
			with self._state_lock:
				self.state = SupervisorState.FAILED_TRIPPED
			diag = self.stderr_buffer.get_text()
			logger.critical(
				"CIRCUIT BREAKER TRIPPED: %d crashes within %.1fs window. Halting restarts.\n"
				"Diagnostics:\n%s",
				len(self._crash_timestamps),
				self.crash_window_seconds,
				diag[-1000:] if diag else "(no stderr output)",
			)
			self._notify_presenter_circuit_breaker_tripped()
			return

		# Exponential backoff restart
		if self.auto_restart and not self._shutdown_event.is_set():
			delay = min(
				self.max_backoff_seconds,
				self.base_backoff_seconds * (2**self._restart_attempts),
			)
			self._restart_attempts += 1
			self.active_generation += 1  # Generation fencing increment

			with self._state_lock:
				self.state = SupervisorState.RESTARTING

			logger.info(
				"Scheduling worker restart attempt %d in %.2fs (new generation=%d)",
				self._restart_attempts,
				delay,
				self.active_generation,
			)
			threading.Thread(
				target=self._delayed_restart,
				args=(delay,),
				name="WorkerDelayedRestart",
				daemon=True,
			).start()

	def _delayed_restart(self, delay: float) -> None:
		"""Wait backoff delay and trigger restart."""
		time.sleep(delay)
		if not self._shutdown_event.is_set() and self.state not in (
			SupervisorState.STOPPED,
			SupervisorState.FAILED_TRIPPED,
		):
			self.start()

	def _notify_presenter_circuit_breaker_tripped(self) -> None:
		"""Marshal non-blocking notification to UI/Presenter."""
		msg = (
			"AI Assistant local worker stopped responding. Background model features "
			"unavailable. Open Settings to view diagnostics or restart."
		)
		if self.on_circuit_breaker_tripped:
			try:
				self.on_circuit_breaker_tripped(msg)
			except Exception as exc:
				logger.error(
					"Error in on_circuit_breaker_tripped callback: %s", exc
				)

		# Try fallback to nvda_ui if available
		try:
			from ..ui import nvda_ui

			nvda_ui.message(msg)
		except Exception:
			pass

	def reset_circuit_breaker(self) -> None:
		"""Reset circuit breaker history and restart counter, allowing fresh start."""
		with self._state_lock:
			self._crash_timestamps.clear()
			self._restart_attempts = 0
			if self.state == SupervisorState.FAILED_TRIPPED:
				self.state = SupervisorState.STOPPED
		logger.info("WorkerSupervisor circuit breaker reset")

	def stop(self) -> None:
		"""Gracefully stop worker process and release all resources within 1.5s."""
		self._shutdown_event.set()
		with self._state_lock:
			self.state = SupervisorState.STOPPED

		# 1. Attempt graceful shutdown command over command pipe (timeout 1.0s)
		try:
			with self._cmd_lock:
				if self._cmd_client and self._cmd_client.is_connected:
					self._cmd_client.write_frame({"type": "shutdown_command"})
		except Exception:
			pass

		# 2. Wait up to 1.0s for clean exit
		self._teardown_process_handles(force_kill=False)
		if get_worker_supervisor() is self:
			set_worker_supervisor(None)
		logger.info("WorkerSupervisor stopped cleanly")

	def _teardown_process_handles(self, force_kill: bool = False) -> None:
		"""Terminate or kill worker process and close pipe handles."""
		if self._worker_client:
			try:
				self._worker_client.disconnect()
			except Exception:
				pass
			self._worker_client = None

		if self._cmd_client:
			self._cmd_client.close()
			self._cmd_client = None
		if self._evt_client:
			self._evt_client.close()
			self._evt_client = None

		if self._process:
			proc = self._process
			self._process = None
			if proc.poll() is None:
				if not force_kill:
					try:
						proc.wait(timeout=1.0)
					except subprocess.TimeoutExpired:
						force_kill = True

				if force_kill and proc.poll() is None:
					try:
						proc.terminate()
						proc.wait(timeout=0.3)
					except Exception:
						pass
					if proc.poll() is None:
						try:
							proc.kill()
						except Exception:
							pass

		if self._job_object:
			self._job_object.close()
			self._job_object = None

	def get_cmd_client(self) -> NamedPipeClient | None:
		"""Return connected command pipe client."""
		return self._cmd_client

	def get_evt_client(self) -> NamedPipeClient | None:
		"""Return connected event pipe client."""
		return self._evt_client

	def get_worker_client(self) -> WorkerClient | None:
		"""Return connected worker client instance."""
		return self._worker_client


_active_supervisor: WorkerSupervisor | None = None
_active_client: WorkerClient | None = None


def get_worker_supervisor() -> WorkerSupervisor | None:
	"""Return the active global WorkerSupervisor instance."""
	global _active_supervisor
	return _active_supervisor


def set_worker_supervisor(supervisor: WorkerSupervisor | None) -> None:
	"""Set the active global WorkerSupervisor instance."""
	global _active_supervisor
	_active_supervisor = supervisor


def get_worker_client() -> WorkerClient | None:
	"""Return the active WorkerClient instance."""
	global _active_client, _active_supervisor
	if _active_client is not None:
		return _active_client
	if _active_supervisor is not None:
		return _active_supervisor.get_worker_client()
	return None


def set_worker_client(client: WorkerClient | None) -> None:
	"""Set the active WorkerClient instance (e.g. for testing)."""
	global _active_client
	_active_client = client

