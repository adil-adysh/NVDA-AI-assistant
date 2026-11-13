"""Private worker client for the Rust rmcp manager's bounded JSON-lines IPC."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
import logging
import os
import queue
import subprocess
import threading
import time
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

MAX_FRAME_BYTES = 1024 * 1024
MAX_PENDING_REQUESTS = 32
PROTOCOL_VERSION = 1


class McpManagerError(RuntimeError):
	"""Base error for manager process and protocol failures."""

	def __init__(self, message: str, *, category: str = "manager_unavailable", uncertain: bool = False) -> None:
		super().__init__(message)
		self.category = category
		self.uncertain = uncertain


class _PendingReply:
	__slots__ = ("event", "value", "error", "operation", "dispatched")

	def __init__(self, operation: str) -> None:
		self.event = threading.Event()
		self.value: dict[str, Any] | None = None
		self.error: McpManagerError | None = None
		self.operation = operation
		self.dispatched = False


class McpManagerClient:
	"""Own one manager subprocess and correlate concurrent request replies.

	The owner is lazy: construction is passive, ``start`` launches and negotiates.
	Only the private worker creates this object.  Its caller must already be off
	NVDA's event thread.
	"""

	def __init__(
		self,
		command: Sequence[str],
		*,
		event_handler: Callable[[dict[str, Any]], None] | None = None,
		popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
	) -> None:
		if not command or not all(isinstance(part, str) and part for part in command):
			raise ValueError("MCP manager command must contain a program and string arguments")
		self._command = tuple(command)
		self._event_handler = event_handler
		self._popen = popen
		self._process: subprocess.Popen[bytes] | None = None
		self._reader: threading.Thread | None = None
		self._state_lock = threading.RLock()
		self._write_lock = threading.Lock()
		self._pending_lock = threading.Lock()
		self._pending: dict[str, _PendingReply] = {}
		self._events: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=128)
		self._started = False
		self._starting = False
		self._startup_complete = threading.Event()
		self._closing = False
		self._failure: McpManagerError | None = None

	@property
	def running(self) -> bool:
		with self._state_lock:
			process = self._process
			return self._started and not self._starting and not self._closing and process is not None and process.poll() is None

	@property
	def failed(self) -> bool:
		with self._state_lock:
			process = self._process
			return self._failure is not None or (self._started and process is not None and process.poll() is not None)

	def start(
		self,
		*,
		timeout: float = 10.0,
		cancellation_requested: Callable[[], bool] | None = None,
	) -> None:
		wait_for_startup = False
		with self._state_lock:
			if self._started:
				if self._failure is not None:
					raise self._failure
				if self._starting:
					wait_for_startup = True
				else:
					return
			if self._closing:
				raise McpManagerError("MCP manager is shutting down", category="shutdown")
			if not wait_for_startup:
				process = self._popen(
					self._command,
					stdin=subprocess.PIPE,
					stdout=subprocess.PIPE,
					stderr=subprocess.DEVNULL,
					bufsize=0,
					creationflags=0x08000000 if os.name == "nt" else 0,
				)
				if process.stdin is None or process.stdout is None:
					process.kill()
					raise McpManagerError("MCP manager pipes were not created")
				self._process = process
				self._started = True
				self._starting = True
				self._startup_complete.clear()
				self._reader = threading.Thread(target=self._read_replies, name="McpManagerReader", daemon=True)
				self._reader.start()
		if wait_for_startup:
			deadline = time.monotonic() + max(0.001, timeout)
			while not self._startup_complete.is_set():
				if cancellation_requested is not None and cancellation_requested():
					raise McpManagerError("MCP manager startup was cancelled", category="cancelled")
				remaining = deadline - time.monotonic()
				if remaining <= 0:
					raise McpManagerError("MCP manager startup negotiation timed out", category="startup_timeout")
				self._startup_complete.wait(min(remaining, 0.05))
			with self._state_lock:
				if self._failure is not None:
					raise self._failure
				if not self.running:
					raise McpManagerError("MCP manager exited during startup")
			return
		try:
			reply = self._send_request(
				{"op": "hello", "protocol_version": PROTOCOL_VERSION},
				timeout=timeout,
				cancellation_requested=cancellation_requested,
			)
			if reply.get("ok") is not True or reply.get("protocol_version") != PROTOCOL_VERSION:
				raise McpManagerError("MCP manager protocol negotiation failed", category="version_mismatch")
			with self._state_lock:
				self._starting = False
				self._startup_complete.set()
		except BaseException:
			self._fail_pending(McpManagerError("MCP manager startup failed"))
			self._stop_process(timeout=1.0)
			with self._state_lock:
				self._failure = McpManagerError("MCP manager startup or protocol negotiation failed")
				self._starting = False
				self._startup_complete.set()
			raise

	def request(
		self,
		command: Mapping[str, Any],
		*,
		timeout: float = 30.0,
		cancellation_requested: Callable[[], bool] | None = None,
	) -> dict[str, Any]:
		if not self.running:
			raise self._failure or McpManagerError("MCP manager is not running")
		return self._send_request(command, timeout=timeout, cancellation_requested=cancellation_requested)

	def next_event(self, timeout: float | None = None) -> dict[str, Any] | None:
		try:
			return self._events.get(timeout=timeout)
		except queue.Empty:
			return None

	def drain_events(self, *, limit: int = 128) -> list[dict[str, Any]]:
		"""Return a bounded batch of asynchronous manager events."""
		if not 1 <= limit <= 128:
			raise ValueError("MCP event batch limit must be between 1 and 128")
		events = []
		for _ in range(limit):
			try:
				events.append(self._events.get_nowait())
			except queue.Empty:
				break
		return events

	def close(self, *, timeout: float = 3.0) -> None:
		with self._state_lock:
			if self._closing:
				return
			self._closing = True
			process = self._process
		started = self._started
		if process is None:
			return
		if started and process.poll() is None:
			try:
				self._send_request({"op": "shutdown"}, timeout=min(timeout, 2.0), allow_closing=True)
			except McpManagerError:
				logger.info("MCP manager did not acknowledge shutdown; terminating owned process")
		self._stop_process(timeout=timeout)
		self._fail_pending(McpManagerError("MCP manager shut down", category="shutdown"))

	def _send_request(
		self,
		command: Mapping[str, Any],
		*,
		timeout: float,
		cancellation_requested: Callable[[], bool] | None = None,
		allow_closing: bool = False,
	) -> dict[str, Any]:
		operation = command.get("op")
		if not isinstance(operation, str) or not operation:
			raise ValueError("MCP manager command requires an operation")
		with self._state_lock:
			if self._closing and not allow_closing:
				raise McpManagerError("MCP manager is shutting down", category="shutdown")
			process = self._process
		if process is None or process.poll() is not None or process.stdin is None:
			raise self._failure or McpManagerError("MCP manager process exited")
		request_id = uuid4().hex
		frame = dict(command)
		frame["id"] = request_id
		payload = json.dumps(frame, ensure_ascii=True, separators=(",", ":")).encode("utf-8") + b"\n"
		if len(payload) > MAX_FRAME_BYTES:
			raise McpManagerError("MCP manager request exceeds the frame limit", category="message_too_large")
		pending = _PendingReply(operation)
		with self._pending_lock:
			if len(self._pending) >= MAX_PENDING_REQUESTS:
				raise McpManagerError("MCP manager request capacity reached", category="capacity")
			self._pending[request_id] = pending
		try:
			with self._write_lock:
				# A write or manager death after this point may follow remote dispatch.
				pending.dispatched = True
				process.stdin.write(payload)
				process.stdin.flush()
		except (OSError, BrokenPipeError) as exc:
			with self._pending_lock:
				self._pending.pop(request_id, None)
			raise McpManagerError("MCP manager command pipe failed", uncertain=operation == "invoke") from exc
		deadline = time.monotonic() + max(0.001, min(float(timeout), 300.0))
		while not pending.event.is_set():
			if cancellation_requested is not None and cancellation_requested():
				if operation == "invoke":
					self._send_cancel(request_id)
				with self._pending_lock:
					self._pending.pop(request_id, None)
				raise McpManagerError("MCP invocation cancellation requested; remote outcome is unknown", category="cancelled", uncertain=operation == "invoke")
			remaining = deadline - time.monotonic()
			if remaining <= 0:
				with self._pending_lock:
					self._pending.pop(request_id, None)
				raise McpManagerError("MCP manager request exceeded its deadline", category="timeout", uncertain=operation == "invoke")
			pending.event.wait(min(remaining, 0.05))
		if pending.error is not None:
			raise pending.error
		if pending.value is None:
			raise McpManagerError("MCP manager returned an empty response", uncertain=operation == "invoke")
		return pending.value

	def _send_cancel(self, target_id: str) -> None:
		try:
			self._send_request({"op": "cancel", "target_id": target_id}, timeout=1.0)
		except McpManagerError:
			pass

	def _read_replies(self) -> None:
		process = self._process
		if process is None or process.stdout is None:
			return
		failure: McpManagerError | None = None
		try:
			while True:
				line = process.stdout.readline(MAX_FRAME_BYTES + 1)
				if not line:
					break
				if len(line) > MAX_FRAME_BYTES or not line.endswith(b"\n"):
					failure = McpManagerError("MCP manager emitted an oversized or incomplete frame", category="invalid_frame")
					break
				try:
					frame = json.loads(line)
				except (UnicodeDecodeError, json.JSONDecodeError):
					failure = McpManagerError("MCP manager emitted invalid JSON", category="invalid_frame")
					break
				if not isinstance(frame, dict):
					failure = McpManagerError("MCP manager frame must be an object", category="invalid_frame")
					break
				request_id = frame.get("id")
				if isinstance(request_id, str):
					with self._pending_lock:
						pending = self._pending.pop(request_id, None)
					if pending is not None:
						pending.value = frame
						pending.event.set()
					continue
				self._deliver_event(frame)
		except OSError as exc:
			failure = McpManagerError("MCP manager event pipe failed")
			logger.debug("MCP manager reader failed: %s", exc)
		finally:
			if failure is None:
				failure = McpManagerError("MCP manager process exited")
			self._failure = failure
			self._fail_pending(failure)

	def _deliver_event(self, frame: dict[str, Any]) -> None:
		try:
			self._events.put_nowait(frame)
		except queue.Full:
			# Losing even one list-change notification makes the local catalog suspect.
			# Replace the queued deltas with one explicit signal so the owner can fetch
			# authoritative catalogs for every connected server.
			while True:
				try:
					self._events.get_nowait()
				except queue.Empty:
					break
			self._events.put_nowait({
				"event": "resync_required",
				"reason": "worker_event_queue_overflow",
			})
			logger.warning("MCP manager event queue overflowed; catalog resynchronization is required")
		if self._event_handler is not None:
			try:
				self._event_handler(frame)
			except Exception:
				logger.exception("MCP manager event handler failed")

	def _fail_pending(self, error: McpManagerError) -> None:
		with self._pending_lock:
			pending = tuple(self._pending.values())
			self._pending.clear()
		for item in pending:
			item.error = McpManagerError(
				str(error),
				category=error.category,
				uncertain=error.uncertain or (item.operation == "invoke" and item.dispatched),
			)
			item.event.set()

	def _stop_process(self, *, timeout: float) -> None:
		process = self._process
		if process is None:
			return
		if process.poll() is None:
			try:
				process.wait(timeout=max(0.01, timeout))
			except subprocess.TimeoutExpired:
				process.terminate()
				try:
					process.wait(timeout=0.5)
				except subprocess.TimeoutExpired:
					process.kill()
					process.wait(timeout=0.5)
		for stream in (process.stdin, process.stdout):
			if stream is not None:
				try:
					stream.close()
				except OSError:
					pass
		reader = self._reader
		if reader is not None and reader is not threading.current_thread():
			reader.join(timeout=0.5)
