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
from uuid import uuid4

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

from ..core.translation import _  # noqa: E402


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
		self.worker_python_path = Path(sys.executable)

		# Locate worker entrypoint
		if worker_script_path is None:
			bundle = Path(__file__).resolve().parents[1] / "worker_host"
			if (bundle / "python.exe").is_file():
				self.worker_python_path = bundle / "python.exe"
			self.worker_script_path = bundle.parent / "worker" / "__main__.py"
		else:
			self.worker_script_path = Path(worker_script_path).resolve()

		# State & Generation
		self.state = SupervisorState.STOPPED
		self.active_generation = 1
		self._restart_attempts = 0
		self._crash_timestamps: deque[float] = deque()
		self._last_pong_monotonic = 0.0
		self._latest_health: WorkerHealth | None = None
		self.last_startup_error: str | None = None

		# Handles & Threads
		self._process: subprocess.Popen[bytes] | None = None
		self._job_object: JobObject | None = None
		self._cmd_client: NamedPipeClient | None = None
		self._evt_client: NamedPipeClient | None = None
		self._worker_client: WorkerClient | None = None
		self._application_owned = False
		self._disposed = False
		self._restart_callback: Callable[[], None] | None = None
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
			if self._disposed:
				return False
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
			self._latest_health = None
			self.last_startup_error = None

		try:
			self._spawn_worker_process()
			if self._disposed:
				raise RuntimeError("Worker owner is closed")
			if auto_connect_pipes:
				self._connect_and_handshake()
			if not self._application_owned:
				set_worker_supervisor(self)
			return True
		except Exception as exc:
			self.last_startup_error = str(exc)
			logger.error("Failed to start worker process: %s", exc)
			if self._disposed:
				self.stop()
				return False
			self._handle_crash(reason=f"STARTUP_ERROR: {exc}")
			return False

	def _spawn_worker_process(self) -> None:
		"""Spawn the worker process enclosed in Windows Job Object."""
		if not self.worker_script_path.is_file():
			raise FileNotFoundError(_("AI Assistant worker bundle is missing; reinstall the add-on"))
		if self.worker_python_path.stem.lower() not in ("python", "pythonw", "python3", "python3.13"):
			raise RuntimeError(_("Private worker Python is missing; cannot launch worker with NVDA's executable"))
		self._job_object = create_worker_job_object()

		module_launch = self.worker_script_path.name == "__main__.py" and self.worker_script_path.parent.name == "worker"
		entrypoint = ["-m", "worker"] if module_launch else [str(self.worker_script_path)]
		cmd = [
			str(self.worker_python_path),
			"-B",
			*entrypoint,
			"--cmd-pipe",
			self.cmd_pipe_name,
			"--evt-pipe",
			self.evt_pipe_name,
			"--parent-pid",
			str(os.getpid()),
			"--generation",
			str(self.active_generation),
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
			cwd=str(self.worker_script_path.parent.parent) if module_launch else None,
			stdin=subprocess.DEVNULL,
			stdout=subprocess.DEVNULL,
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
			raw_resp = self._cmd_client.read_frame(timeout_seconds=self.connect_timeout_seconds)

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
			if self._disposed:
				raise RuntimeError("Worker owner is closed")
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
					resp_frame = self._cmd_client.read_frame(timeout_seconds=self.liveness_timeout_seconds)

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
				SupervisorState.CRASHED,
			):
				return
			self.state = SupervisorState.CRASHED

		logger.warning("Worker failure detected: %s", reason)

		# Capture exit diagnostics
		self._teardown_process_handles(force_kill=True)
		# Report the first failure in a recovery episode, not only the circuit breaker.
		if not self._crash_timestamps or time.monotonic() - self._crash_timestamps[-1] > self.crash_window_seconds:
			try:
				from ..ui import nvda_ui
				nvda_ui.queue(nvda_ui.message, _("The local AI worker stopped unexpectedly. The current request may have failed. Please try again."))
			except Exception:
				logger.debug("Unable to queue worker failure feedback", exc_info=True)

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
			if self._restart_callback is not None:
				self._restart_callback()
			else:
				self.start()

	def _notify_presenter_circuit_breaker_tripped(self) -> None:
		"""Marshal non-blocking notification to UI/Presenter."""
		msg = _(
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

			nvda_ui.queue(nvda_ui.message, msg)
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
			acquired = self._cmd_lock.acquire(timeout=0.1)
			try:
				if acquired and self._cmd_client and self._cmd_client.is_connected:
					self._cmd_client.write_frame({"type": "shutdown_command"})
			finally:
				if acquired:
					self._cmd_lock.release()
		except Exception:
			pass

		# 2. Wait up to 1.0s for clean exit
		self._teardown_process_handles(force_kill=False)
		if get_worker_supervisor() is self:
			set_worker_supervisor(None)
		logger.info("WorkerSupervisor stopped cleanly")

	def disable_startup(self) -> None:
		"""Permanently fence this application owner's launches before async teardown."""
		with self._state_lock:
			self._disposed = True
			self._shutdown_event.set()

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
_worker_owner: LazyWorkerOwner | None = None
_worker_shutdown = False


class LazyWorkerOwner:
	"""One application-owned startup attempt, shared by background operations.

	Registration and lookup are passive. Explicit prelaunch uses the same path
	as an operation, allowing startup policy to evolve without another owner.
	"""

	def __init__(self, supervisor: WorkerSupervisor) -> None:
		self.supervisor = supervisor
		self.supervisor._application_owned = True
		self.supervisor._restart_callback = self._restart
		self._condition = threading.Condition()
		self._starting = False
		self._closed = False
		self._error: str | None = None
		self._shutdown_thread: threading.Thread | None = None

	def get_client(self) -> WorkerClient | None:
		with self._condition:
			if self._closed or self._starting:
				return None
			return self.supervisor.get_worker_client() if self.supervisor.is_running else None

	def ensure_client(self) -> WorkerClient:
		with self._condition:
			while self._starting and not self._closed:
				self._condition.wait()
			if self._closed:
				raise RuntimeError("Worker owner is closed")
			client = self.get_client()
			if client is not None:
				return client
			if self._error is not None:
				raise RuntimeError(self._error)
			self._starting = True
		try:
			if not self.supervisor.start():
				details = self.supervisor.stderr_buffer.get_text()[-1000:] or getattr(self.supervisor, "last_startup_error", None)
				raise RuntimeError(_("Could not start AI Assistant worker. {details}").format(details=details))
			client = self.supervisor.get_worker_client()
			if client is None:
				raise RuntimeError(_("Worker startup did not establish a connection"))
		except Exception as exc:
			with self._condition:
				self._error = _("Worker startup failed: {error}").format(error=exc)
				raise RuntimeError(self._error) from exc
		finally:
			with self._condition:
				self._starting = False
				closed = self._closed
				self._condition.notify_all()
			if closed:
				self.supervisor.stop()
		if closed:
			raise RuntimeError("Worker owner is closed")
		return client

	def start_in_background(self) -> threading.Thread:
		def launch() -> None:
			try:
				self.ensure_client()
			except RuntimeError:
				logger.exception("Background worker startup failed")
		thread = threading.Thread(target=launch, name="AIWorkerStartup", daemon=True)
		thread.start()
		return thread

	def _restart(self) -> None:
		with self._condition:
			if self._closed:
				return
			self._error = None
		try:
			self.ensure_client()
		except RuntimeError:
			logger.exception("Worker recovery failed")

	def close(self) -> threading.Thread:
		with self._condition:
			if self._shutdown_thread is not None:
				return self._shutdown_thread
			self._closed = True
			disable = getattr(self.supervisor, "disable_startup", None)
			if callable(disable):
				disable()
			self._condition.notify_all()
			self._shutdown_thread = threading.Thread(target=self.supervisor.stop, name="AIWorkerShutdown", daemon=True)
			self._shutdown_thread.start()
			return self._shutdown_thread


def configure_worker_owner(*, start_on_startup: bool = False) -> LazyWorkerOwner:
	"""Register a passive owner; optional worker prelaunch is independent of servers."""
	global _worker_owner, _worker_shutdown
	if _worker_owner is not None:
		return _worker_owner
	_worker_shutdown = False
	token = f"{os.getpid()}_{uuid4().hex}"
	_worker_owner = LazyWorkerOwner(WorkerSupervisor(
		cmd_pipe_name=rf"\\.\pipe\nvda_ai_worker_cmd_{token}",
		evt_pipe_name=rf"\\.\pipe\nvda_ai_worker_evt_{token}",
	))
	if start_on_startup:
		_worker_owner.start_in_background()
	return _worker_owner


def ensure_worker_client() -> WorkerClient:
	if _worker_shutdown:
		raise RuntimeError("Worker owner is closed")
	client = get_worker_client()
	if client is not None:
		return client
	if _worker_owner is None:
		raise RuntimeError("AI Assistant worker lifecycle has not been configured")
	return _worker_owner.ensure_client()


def get_worker_client_for_operation() -> WorkerClient | None:
	"""Operations use the owner; standalone developer callers may use direct I/O."""
	if _worker_owner is not None or _worker_shutdown:
		return ensure_worker_client()
	return get_worker_client()


def shutdown_worker_owner() -> None:
	"""Reject new operations immediately and release process handles in background."""
	global _worker_owner, _worker_shutdown
	_worker_shutdown = True
	owner, _worker_owner = _worker_owner, None
	if owner is not None:
		owner.close()


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
	if _worker_shutdown:
		return None
	if _active_client is not None:
		return _active_client
	if _worker_owner is not None:
		return _worker_owner.get_client()
	if _active_supervisor is not None:
		return _active_supervisor.get_worker_client()
	return None


def set_worker_client(client: WorkerClient | None) -> None:
	"""Set the active WorkerClient instance (e.g. for testing)."""
	global _active_client
	_active_client = client

