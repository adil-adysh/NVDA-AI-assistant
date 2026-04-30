# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from .host_protocol import HostEvent

logger = logging.getLogger(__name__)


class HostPipeTransport:
	def __init__(
		self,
		pipe_name: str,
		event_pipe_name: str | None = None,
		event_callback: Callable[[HostEvent], None] | None = None,
	) -> None:
		self._pipe_name = pipe_name
		self._event_pipe_name = event_pipe_name
		self._event_callback = event_callback
		self._event_listener_started = False
		self._event_listener_lock = threading.Lock()

	def send(self, message: bytes) -> bytes:
		return self.send_and_receive(message)

	def start_event_listener(self) -> None:
		if self._event_callback is None or not self._event_pipe_name:
			return
		with self._event_listener_lock:
			if self._event_listener_started:
				return
			thread = threading.Thread(
				target=self._event_listener_loop,
				name="ui_host_event_listener",
				daemon=True,
			)
			thread.start()
			self._event_listener_started = True

	def send_and_receive(self, message: bytes) -> bytes:
		request_id = self._extract_request_id(message)
		if not request_id:
			raise ValueError("Message must include an id or request_id for correlation")

		import win32file
		import win32pipe

		handle = self._connect(self._pipe_name, win32file, win32pipe)
		try:
			logger.debug("HostPipeTransport sending request_id=%s payload_len=%s", request_id, len(message))
			win32file.WriteFile(handle, message)
			logger.debug("HostPipeTransport wrote %d bytes for request_id=%s", len(message), request_id)
			response = self._read_response(handle, win32file)
			logger.debug("HostPipeTransport received %d response bytes for request_id=%s", len(response), request_id)
			return response
		finally:
			self._close_handle(handle, win32file)

	def _connect(self, pipe_name: str, win32file_module: Any, win32pipe_module: Any) -> Any:
		logger.debug("HostPipeTransport connecting to pipe %s", pipe_name)
		self._wait_for_pipe(pipe_name, win32pipe_module)
		last_error: Exception | None = None
		for attempt in range(5):
			try:
				handle = win32file_module.CreateFile(
					pipe_name,
					win32file_module.GENERIC_READ | win32file_module.GENERIC_WRITE,
					0,
					None,
					win32file_module.OPEN_EXISTING,
					0,
					None,
				)
				self._set_message_mode(handle, win32pipe_module)
				logger.debug("HostPipeTransport connected handle=%s", handle)
				return handle
			except Exception as error:
				last_error = error
				winerror = getattr(error, "winerror", None)
				if winerror in (2, 231):
					logger.warning("HostPipeTransport pipe not ready (winerror=%s) attempt %s/5", winerror, attempt + 1, exc_info=True)
				else:
					logger.warning("HostPipeTransport connection attempt %s/5 failed: %s", attempt + 1, error, exc_info=True)
				if attempt < 4:
					time.sleep(0.25)
					continue
				break
		raise RuntimeError(f"Unable to connect to host pipe: {last_error}")

	def _event_listener_loop(self) -> None:
		if not self._event_pipe_name or self._event_callback is None:
			return

		import win32file
		import win32pipe

		logger.debug("HostPipeTransport event listener starting for pipe %s", self._event_pipe_name)
		while True:
			try:
				handle = self._connect(self._event_pipe_name, win32file, win32pipe)
			except Exception as error:
				logger.debug("HostPipeTransport event listener waiting for pipe %s: %s", self._event_pipe_name, error)
				time.sleep(0.5)
				continue

			try:
				while True:
					payload = self._read_line(handle, win32file, timeout_seconds=None)
					if not payload:
						break
					self._dispatch_event(payload)
			except Exception as error:
				logger.debug("HostPipeTransport event listener disconnected from %s: %s", self._event_pipe_name, error)
			finally:
				self._close_handle(handle, win32file)

	def _dispatch_event(self, payload: bytes) -> None:
		if self._event_callback is None:
			return
		try:
			event = HostEvent.from_json(payload.decode("utf-8", errors="replace"))
		except Exception as error:
			logger.warning("HostPipeTransport received invalid host event: %s", error, exc_info=True)
			return
		try:
			self._event_callback(event)
		except Exception:
			logger.exception("HostPipeTransport event callback failed")

	def _read_response(self, handle: Any, win32file_module: Any) -> bytes:
		return self._read_line(handle, win32file_module, timeout_seconds=5.0)

	def _read_line(self, handle: Any, win32file_module: Any, timeout_seconds: float | None) -> bytes:
		deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
		buffer = b""
		while deadline is None or time.monotonic() < deadline:
			try:
				_, chunk = win32file_module.ReadFile(handle, 4096)
			except Exception as error:
				if self._is_pipe_closed_error(error):
					raise RuntimeError("Host pipe closed before a response was received") from error
				raise

			if not chunk:
				raise RuntimeError("Host pipe returned an empty response")

			buffer += chunk
			if b"\n" in buffer:
				line, _ = buffer.split(b"\n", 1)
				return line

		timeout_label = "without timeout" if timeout_seconds is None else f"after {timeout_seconds} seconds"
		raise TimeoutError(f"Timed out waiting for host response on pipe {self._pipe_name} {timeout_label}")

	def _extract_request_id(self, message: bytes) -> str | None:
		try:
			payload = json.loads(message.decode("utf-8", errors="replace"))
			if isinstance(payload, dict):
				return payload.get("id") or payload.get("request_id")
		except Exception:
			return None
		return None

	def _close_handle(self, handle: Any, win32file_module: Any) -> None:
		try:
			win32file_module.CloseHandle(handle)
		except Exception as error:
			logger.debug("HostPipeTransport failed to close handle: %s", error, exc_info=True)

	def _wait_for_pipe(self, pipe_name: str, win32pipe_module: Any, timeout_seconds: float = 5.0) -> None:
		logger.debug("HostPipeTransport waiting for pipe %s up to %s seconds", pipe_name, timeout_seconds)
		deadline = time.monotonic() + timeout_seconds
		last_error: Exception | None = None
		while time.monotonic() < deadline:
			try:
				win32pipe_module.WaitNamedPipe(pipe_name, 250)
				return
			except Exception as error:
				last_error = error
				logger.debug("HostPipeTransport wait failed for %s: %s", pipe_name, error)
				time.sleep(0.1)
		raise TimeoutError(f"Timed out waiting for pipe {pipe_name}: {last_error}")

	def _is_pipe_closed_error(self, error: Exception) -> bool:
		winerror = getattr(error, "winerror", None)
		return winerror in (109, 232)

	def _set_message_mode(self, handle: Any, win32pipe_module: Any) -> None:
		try:
			win32pipe_module.SetNamedPipeHandleState(handle, win32pipe_module.PIPE_READMODE_MESSAGE, None, None)
			logger.debug("HostPipeTransport set message read mode")
		except Exception as error:
			logger.debug("HostPipeTransport could not set message read mode: %s", error)
