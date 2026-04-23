# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from .host_protocol import HostEvent, HostResponse

logger = logging.getLogger(__name__)

_HANDLE_STATE_DISCONNECTED = "disconnected"
_HANDLE_STATE_CONNECTED = "connected"
_HANDLE_STATE_CLOSING = "closing"
_HANDLE_STATE_CLOSED = "closed"

class HostPipeTransport:
	def __init__(self, pipe_name: str, event_callback: Callable[[HostEvent], None] | None = None) -> None:
		self._pipe_name = pipe_name
		self._event_callback = event_callback
		self._handle: Any | None = None
		self._reader_thread: threading.Thread | None = None
		self._lock = threading.Lock()
		self._connection_state = _HANDLE_STATE_DISCONNECTED
		self._active_writes = 0
		self._response_events: dict[str, threading.Event] = {}
		self._response_values: dict[str, bytes] = {}

	def send_and_receive(self, message: bytes) -> bytes:
		request_id = self._extract_request_id(message)
		if not request_id:
			raise ValueError("Message must include an id or request_id for correlation")

		logger.debug("HostPipeTransport send_and_receive start request_id=%s payload_len=%s", request_id, len(message))
		with self._lock:
			response_event = threading.Event()
			self._response_events[request_id] = response_event

		try:
			self._write_message(message)
			if not response_event.wait(5.0):
				raise TimeoutError(f"Timed out waiting for host response for request {request_id}")

			with self._lock:
				response = self._response_values.pop(request_id, None)
			if response is None:
				raise RuntimeError(f"Missing response for request {request_id}")
			logger.debug("HostPipeTransport received response for request_id=%s", request_id)
			return response
		finally:
			with self._lock:
				self._response_events.pop(request_id, None)
				self._response_values.pop(request_id, None)

	def send(self, message: bytes) -> bytes:
		print("STEP 5: INSIDE transport.send")
		return self.send_and_receive(message)

	def _extract_request_id(self, message: bytes) -> str | None:
		try:
			payload = json.loads(message.decode("utf-8", errors="replace"))
			if isinstance(payload, dict):
				return payload.get("id") or payload.get("request_id")
		except Exception:
			return None
		return None

	def _write_message(self, message: bytes) -> None:
		print("STEP 6: WRITE_MESSAGE CALLED")
		import win32file
		import win32pipe

		logger.debug(
			"HostPipeTransport _write_message start active_writes=%s connection_state=%s message_len=%s",
			self._active_writes,
			self._connection_state,
			len(message),
		)
		self._ensure_connected(win32file, win32pipe)
		with self._lock:
			if self._handle is None or self._connection_state != _HANDLE_STATE_CONNECTED:
				raise RuntimeError("Host pipe handle unavailable")
			handle = self._handle
			self._active_writes += 1

		try:
			win32file.WriteFile(handle, message)
			logger.debug("HostPipeTransport wrote %d bytes", len(message))
		except Exception as error:
			if self._is_pipe_closed_error(error):
				logger.debug("HostPipeTransport write failed because pipe is closing: %s", error)
			else:
				logger.warning("HostPipeTransport write failed: %s", error, exc_info=True)
			self._mark_connection_broken()
			raise
		finally:
			with self._lock:
				self._active_writes -= 1
				if self._connection_state == _HANDLE_STATE_CLOSING and self._active_writes == 0:
					self._close_handle()

	def _ensure_connected(self, win32file_module: object, win32pipe_module: object) -> None:
		with self._lock:
			if self._handle is not None and self._reader_thread is not None and self._reader_thread.is_alive():
				logger.debug("HostPipeTransport already connected and reader alive")
				return

		logger.debug("HostPipeTransport ensuring connection for pipe %s", self._pipe_name)
		self._wait_for_pipe(win32pipe_module)
		for attempt in range(5):
			try:
				handle = win32file_module.CreateFile(
					self._pipe_name,
					win32file_module.GENERIC_READ | win32file_module.GENERIC_WRITE,
					0,
					None,
					win32file_module.OPEN_EXISTING,
					0,
					None,
				)
				logger.debug("HostPipeTransport opened handle=%s", handle)
				self._set_message_mode(handle, win32pipe_module)
				with self._lock:
					self._handle = handle
					self._connection_state = _HANDLE_STATE_CONNECTED
				self._start_reader_thread()
				return
			except Exception as error:
				winerror = getattr(error, "winerror", None)
				if winerror in (2, 231):
					logger.warning("HostPipeTransport pipe not ready (winerror=%s) attempt %s/5", winerror, attempt + 1, exc_info=True)
				else:
					logger.warning("HostPipeTransport connection attempt %s/5 failed: %s", attempt + 1, error, exc_info=True)
				if attempt < 4:
					time.sleep(0.25)
					continue
				break

		raise RuntimeError("Unable to connect to host pipe")

	def _start_reader_thread(self) -> None:
		if self._reader_thread and self._reader_thread.is_alive():
			logger.debug("HostPipeTransport reader thread already running")
			return
		logger.debug("HostPipeTransport launching reader thread")
		self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
		self._reader_thread.start()
		logger.debug("HostPipeTransport started reader thread")

	def _reader_loop(self) -> None:
		import win32file

		with self._lock:
			handle = self._handle
		if handle is None:
			return

		buffer = b""
		while True:
			try:
				result = win32file.ReadFile(handle, 4096)
				chunk = result[1]
			except Exception as error:
				if self._is_pipe_closed_error(error):
					logger.debug("HostPipeTransport reader ended normally because pipe closed: %s", error)
				else:
					logger.warning("HostPipeTransport read failed: %s", error, exc_info=True)
				self._mark_connection_broken()
				break

			if not chunk:
				logger.debug("HostPipeTransport read returned empty chunk, ending reader")
				self._mark_connection_broken()
				break

			buffer += chunk
			while b"\n" in buffer:
				line, buffer = buffer.split(b"\n", 1)
				text = line.decode("utf-8", errors="replace").strip()
				if text:
					self._process_frame(text)

	def _process_frame(self, frame: str) -> None:
		try:
			response = HostResponse.from_json(frame)
			self._deliver_response(response, frame.encode("utf-8"))
			return
		except ValueError:
			pass

		try:
			event = HostEvent.from_json(frame)
			if self._event_callback:
				logger.debug("HostPipeTransport delivering event: %s", event.event)
				try:
					self._event_callback(event)
				except Exception as error:
					logger.exception("HostPipeTransport event callback failed")
			return
		except ValueError:
			logger.debug("HostPipeTransport dropped unknown frame: %s", frame)

	def _deliver_response(self, response: HostResponse, payload: bytes) -> None:
		with self._lock:
			if response.request_id in self._response_events:
				logger.debug("HostPipeTransport matched response for request_id=%s", response.request_id)
				self._response_values[response.request_id] = payload
				self._response_events[response.request_id].set()
			else:
				logger.warning("HostPipeTransport dropped unmatched response for request %s", response.request_id)

	def _mark_connection_broken(self) -> None:
		with self._lock:
			if self._connection_state != _HANDLE_STATE_CONNECTED:
				return
			self._connection_state = _HANDLE_STATE_CLOSING
			if self._active_writes == 0:
				self._close_handle()

	def _close_handle(self) -> None:
		with self._lock:
			if self._handle is None:
				self._connection_state = _HANDLE_STATE_CLOSED
				return
			if self._active_writes > 0:
				self._connection_state = _HANDLE_STATE_CLOSING
				return
			handle = self._handle
			self._handle = None
			self._connection_state = _HANDLE_STATE_CLOSED

		logger.debug("HostPipeTransport closing handle")
		try:
			import win32file
			win32file.CloseHandle(handle)
		except Exception as error:
			logger.debug("HostPipeTransport failed to close handle: %s", error, exc_info=True)

	def _wait_for_pipe(self, win32pipe_module: object, timeout_seconds: float = 5.0) -> None:
		logger.debug("HostPipeTransport waiting for pipe %s up to %s seconds", self._pipe_name, timeout_seconds)
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

	def _is_pipe_closed_error(self, error: Exception) -> bool:
		winerror = getattr(error, "winerror", None)
		return winerror in (109, 232)

	def _set_message_mode(self, handle: object, win32pipe_module: object) -> None:
		try:
			win32pipe_module.SetNamedPipeHandleState(handle, win32pipe_module.PIPE_READMODE_MESSAGE, None, None)
			logger.debug("HostPipeTransport set message read mode")
		except Exception as error:
			logger.debug("HostPipeTransport could not set message read mode: %s", error)
