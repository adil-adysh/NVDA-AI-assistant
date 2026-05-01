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
_HOST_COMMAND_PIPE_NAME = r"\\.\pipe\nvda_ai_assistant_ui_cmd"


def get_host_executable_path() -> Path:
	current_dir = Path(__file__).resolve().parent
	host_path = current_dir.parent / "ui_host" / "nvda_ui_host.exe"
	return host_path


def _drain_host_output(process: subprocess.Popen) -> None:
	if process.stdout is None:
		return

	for raw_line in process.stdout:
		line = raw_line.rstrip("\r\n")
		if line:
			logger.info("UI host stdout: %s", line)


def _wait_for_host_pipe_ready(timeout_seconds: float = 5.0) -> None:
	try:
		import win32pipe
	except ImportError:
		logger.debug("pywin32 unavailable; skipping host pipe readiness wait")
		return

	logger.debug("Waiting for UI host pipe readiness: %s (timeout=%ss)", _HOST_COMMAND_PIPE_NAME, timeout_seconds)
	deadline = time.monotonic() + timeout_seconds
	last_error: Exception | None = None
	while time.monotonic() < deadline:
		with _process_lock:
			process = _host_process
		if process is not None and process.poll() is not None:
			raise HostUnavailableError(f"UI host exited during startup with code {process.returncode}")
		try:
			win32pipe.WaitNamedPipe(_HOST_COMMAND_PIPE_NAME, 250)
			logger.info("UI host pipe is ready: %s", _HOST_COMMAND_PIPE_NAME)
			return
		except Exception as error:
			last_error = error
			logger.debug("UI host pipe not ready yet: %s", error)
			time.sleep(0.1)

	raise HostUnavailableError(f"UI host pipe did not become ready: {last_error}")


def start_host_if_needed() -> None:
	global _host_process
	global _host_logger_thread
	process: subprocess.Popen | None = None
	with _process_lock:
		if _host_process is not None and _host_process.poll() is None:
			logger.debug("Reusing existing UI host process pid=%s", _host_process.pid)
			return

		host_exe = get_host_executable_path()
		logger.debug("Looking for UI host executable at %s", host_exe)
		if not host_exe.exists():
			raise HostUnavailableError(f"UI host executable not found: {host_exe}")

		startupinfo = subprocess.STARTUPINFO()
		startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
		startupinfo.wShowWindow = subprocess.SW_HIDE

		try:
			process = subprocess.Popen(
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
			raise HostUnavailableError(f"Unable to start UI host: {error}") from error

	if process is None:
		raise HostUnavailableError("UI host process failed to start")

	try:
		_wait_for_host_pipe_ready()
	except Exception:
		with _process_lock:
			if _host_process is process:
				try:
					if process.poll() is None:
						process.terminate()
				except Exception:
					pass
				_host_process = None
		raise


def stop_host() -> None:
	global _host_process
	with _process_lock:
		if _host_process is None:
			return

		try:
			if _host_process.poll() is None:
				_host_process.terminate()
				_host_process.wait(timeout=5)
		except Exception:
			try:
				_host_process.kill()
			except Exception:
				pass
		finally:
			_host_process = None
