# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


class HostPipeTransport:
	def __init__(self, pipe_name: str) -> None:
		self._pipe_name = pipe_name

	def send_and_receive(self, message: bytes) -> bytes:
		import win32file
		import win32pipe

		last_error: Exception | None = None
		for attempt in range(5):
			try:
				self._wait_for_pipe(win32pipe)
				handle = win32file.CreateFile(
					self._pipe_name,
					win32file.GENERIC_READ | win32file.GENERIC_WRITE,
					0,
					None,
					win32file.OPEN_EXISTING,
					0,
					None,
				)
				logger.debug("HostPipeTransport opened handle=%s", handle)
				try:
					self._set_message_mode(handle, win32pipe)
					win32file.WriteFile(handle, message)
					logger.debug("HostPipeTransport wrote %d bytes", len(message))
					return self._read_message(win32file, handle)
				finally:
					win32file.CloseHandle(handle)
					logger.debug("HostPipeTransport closed handle=%s", handle)
			except Exception as error:
				last_error = error
				winerror = getattr(error, "winerror", None)
				if winerror in (2, 231):
					logger.warning("HostPipeTransport pipe not ready (winerror=%s) attempt %s/5", winerror, attempt + 1, exc_info=True)
				else:
					logger.warning("HostPipeTransport attempt %s/5 failed: %s", attempt + 1, error, exc_info=True)
				if attempt < 4:
					time.sleep(0.25)
					continue
				break

		if last_error is not None:
			raise last_error
		raise RuntimeError("Host pipe transport failed")

	def _wait_for_pipe(self, win32pipe_module: object, timeout_seconds: float = 5.0) -> None:
		deadline = time.monotonic() + timeout_seconds
		last_error: Exception | None = None
		while time.monotonic() < deadline:
			try:
				win32pipe_module.WaitNamedPipe(self._pipe_name, 250)
				return
			except Exception as error:
				last_error = error
				logger.debug("HostPipeTransport wait failed for %s: %s", self._pipe_name, error)
				time.sleep(0.1)
		raise TimeoutError(f"Timed out waiting for pipe {self._pipe_name}: {last_error}")

	def _set_message_mode(self, handle: object, win32pipe_module: object) -> None:
		try:
			win32pipe_module.SetNamedPipeHandleState(handle, win32pipe_module.PIPE_READMODE_MESSAGE, None, None)
			logger.debug("HostPipeTransport set message read mode")
		except Exception as error:
			logger.debug("HostPipeTransport could not set message read mode: %s", error)

	def _read_message(self, win32file_module: object, handle: object) -> bytes:
		response_bytes = b""
		while True:
			result = win32file_module.ReadFile(handle, 4096)
			chunk = result[1]
			if not chunk:
				break
			response_bytes += chunk
			if b"\n" in chunk:
				break
		return response_bytes
