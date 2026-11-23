# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from .host_protocol import HostUnavailableError

logger = logging.getLogger(__name__)
_host_process: Optional[subprocess.Popen] = None
_host_logger_thread: Optional[threading.Thread] = None
_process_lock = threading.Lock()
_shutdown = False
_HOST_COMMAND_PIPE_NAME = r"\\.\pipe\nvda_ai_assistant_ui_cmd"


def configure_host_lifecycle() -> None:
	"""Enable launches for a new application lifecycle."""
	global _shutdown
	with _process_lock:
		_shutdown = False


def fence_host_startup() -> None:
	"""Reject late presentation launches before other owners begin teardown."""
	global _shutdown
	with _process_lock:
		_shutdown = True


def get_host_executable_path() -> Path:
	current_dir = Path(__file__).resolve().parent
	host_path = current_dir.parent / "ui_host" / "nvda_ui_host.exe"
	return host_path


def _drain_host_output(process: subprocess.Popen) -> None:
	if process.stdout is None:
		return

	with process.stdout:
		for raw_line in process.stdout:
			line = raw_line.rstrip("\r\n")
			if line:
				logger.info("UI host pid=%s: %s", process.pid, line)
	try:
		code = process.wait(timeout=0.25)
	except subprocess.TimeoutExpired:
		logger.warning("UI host output closed while pid=%s was still running", process.pid)
	else:
		logger.debug("UI host pid=%s exited with code %#x", process.pid, code & 0xFFFFFFFF)


def _wait_for_host_pipe_ready(process: subprocess.Popen, timeout_seconds: float = 5.0) -> None:
	try:
		import win32pipe
	except ImportError:
		raise HostUnavailableError("UI host named-pipe support is unavailable", stage="startup") from None

	logger.debug(
		"Waiting for UI host pipe readiness: %s (timeout=%ss)", _HOST_COMMAND_PIPE_NAME, timeout_seconds
	)
	deadline = time.monotonic() + timeout_seconds
	last_error: Exception | None = None
	while time.monotonic() < deadline:
		with _process_lock:
			if _shutdown or _host_process is not process:
				raise HostUnavailableError("UI host startup was cancelled", stage="shutdown")
		if (code := process.poll()) is not None:
			raise HostUnavailableError(f"UI host pid={process.pid} exited during startup with code {code:#x}", stage="startup")
		try:
			win32pipe.WaitNamedPipe(_HOST_COMMAND_PIPE_NAME, 250)
			logger.info("UI host pipe is ready: %s", _HOST_COMMAND_PIPE_NAME)
			return
		except Exception as error:
			last_error = error
			time.sleep(0.1)

	raise HostUnavailableError(f"UI host pid={process.pid} command pipe did not become ready: {last_error}", stage="startup")


def start_host_if_needed() -> None:
	global _host_process  # pylint: disable=global-statement
	global _host_logger_thread  # pylint: disable=global-statement
	process: subprocess.Popen | None = None
	with _process_lock:
		if _shutdown:
			raise HostUnavailableError("UI host shutdown has fenced startup", stage="shutdown")
		if _host_process is not None and _host_process.poll() is None:
			logger.debug("Reusing existing UI host process pid=%s", _host_process.pid)
			return

		host_exe = get_host_executable_path()
		logger.debug("Looking for UI host executable at %s", host_exe)
		if not host_exe.exists():
			raise HostUnavailableError(f"UI host executable not found: {host_exe}", stage="missing")

		startupinfo = subprocess.STARTUPINFO()
		startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
		startupinfo.wShowWindow = subprocess.SW_HIDE

		try:
			# The process handle must outlive this function (it is stored in
			# the module-global _host_process), so `with` cannot be used.
			process = subprocess.Popen(  # pylint: disable=consider-using-with
				[str(host_exe)],
				cwd=str(host_exe.parent),
				startupinfo=startupinfo,
				creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
				stdout=subprocess.PIPE,
				stderr=subprocess.STDOUT,
				text=True,
				encoding="utf-8",
				errors="replace",
				bufsize=1,
			)
			_host_process = process
			logger.info("Started UI host process pid=%s", process.pid)
			if process.stdout is not None:
				_host_logger_thread = threading.Thread(
					target=_drain_host_output,
					args=(process,),
					name="ui_host_stdout_reader",
					daemon=True,
				)
				_host_logger_thread.start()
		except Exception as error:
			if process is not None and _host_process is process:
				_stop_owned_host_locked()
			raise HostUnavailableError(f"Unable to start UI host: {error}", stage="startup") from error

	if process is None:
		raise HostUnavailableError("UI host process failed to start", stage="startup")

	try:
		_wait_for_host_pipe_ready(process)
		with _process_lock:
			if _shutdown or _host_process is not process:
				raise HostUnavailableError("UI host startup was cancelled", stage="shutdown")
	except Exception:
		with _process_lock:
			if _host_process is process:
				_stop_owned_host_locked()
		raise


def is_host_process_alive() -> bool:
	"""Return True if the host subprocess is still running."""
	with _process_lock:
		return _host_process is not None and _host_process.poll() is None


def stop_host() -> None:
	global _shutdown
	with _process_lock:
		_shutdown = True
		_stop_owned_host_locked()


def discard_failed_host() -> None:
	"""Retire the owned host after transport failure and allow a later launch."""
	with _process_lock:
		_stop_owned_host_locked()


def _stop_owned_host_locked() -> None:
	global _host_process
	process = _host_process
	if process is None:
		return
	try:
		if process.poll() is None:
			process.terminate()
			process.wait(timeout=1.0)
	except Exception:
		try:
			process.kill()
			process.wait(timeout=1.0)
		except Exception:
			logger.warning("Could not terminate the owned UI host", exc_info=True)
	finally:
		_host_process = None
