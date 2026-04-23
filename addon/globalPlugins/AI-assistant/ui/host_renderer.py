# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
from typing import Any, Callable
from uuid import uuid4

from .host_interface import UIHostRenderer

logger = logging.getLogger(__name__)
from .host_process import start_host_if_needed
from .host_protocol import (
    EVENT_CHAT_SUBMITTED,
    HostCommand,
    HostEvent,
    HostResponse,
    HostUnavailableError,
)
from .host_transport import HostPipeTransport


class HostRenderer(UIHostRenderer):
	PIPE_NAME = r"\\.\pipe\nvda_ai_assistant_ui"

	def __init__(self) -> None:
		self._current_conversation_id: str | None = None
		self._current_use_case_id: str | None = None
		self._chat_submission_handler: Callable[[str, str | None], None] | None = None
		self._transport = HostPipeTransport(self.PIPE_NAME, event_callback=self._on_host_event)
		self._host_ready = False

	def render_display_result(
		self,
		use_case_id: str | None,
		title: str,
		output_text: str | None = None,
		output_html: str | None = None,
		is_html: bool = False,
		success: bool = True,
		message: str | None = None,
		close_button: bool = True,
		copy_button: bool = True,
		copy_text: str | None = None,
		copy_html: str | None = None,
		metadata: dict[str, Any] | None = None,
	) -> None:
		print("STEP 1: ENTER render_display")
		print("STEP 2: transport =", self._transport)
		print("STEP 3: transport is None?", self._transport is None)
		logger.debug("HostRenderer.render_display_result called use_case_id=%s title=%s", use_case_id, title)
		payload = {
			"use_case_id": use_case_id,
			"title": title,
			"success": success,
			"message": message,
			"output_text": output_text,
			"output_html": output_html,
			"is_html": is_html,
			"close_button": close_button,
			"copy_button": copy_button,
			"copy_text": copy_text,
			"copy_html": copy_html,
			"metadata": metadata,
		}
		self._send_command("render_display", payload)

	def open_chat(
		self,
		use_case_id: str | None,
		title: str,
		initial_text: str | None = None,
		initial_image_base64: str | None = None,
		coordinator: Any | None = None,
		tool_registry: Any | None = None,
		metadata: dict[str, Any] | None = None,
	) -> None:
		self._current_use_case_id = use_case_id
		conversation_id = None
		if isinstance(metadata, dict):
			conversation_id = metadata.get("conversation_id")
		self._current_conversation_id = conversation_id or str(uuid4())
		payload = {
			"use_case_id": use_case_id,
			"conversation_id": self._current_conversation_id,
			"title": title,
			"initial_text": initial_text,
			"initial_image_base64": initial_image_base64,
			"metadata": metadata,
		}
		self._send_command("open_chat", payload)

	def register_chat_submission_handler(self, handler: Callable[[str, str | None], None]) -> None:
		self._chat_submission_handler = handler

	def _on_host_event(self, event: HostEvent) -> None:
		if event.event != EVENT_CHAT_SUBMITTED:
			logger.debug("HostRenderer received unsupported host event: %s", event.event)
			return

		message = event.payload.get("message")
		conversation_id = event.payload.get("conversation_id") or self._current_conversation_id
		if not isinstance(message, str) or not message.strip():
			logger.warning("Received chat_submitted event without a message")
			return

		if self._chat_submission_handler is None:
			logger.warning("HostRenderer has no chat submission handler registered")
			return

		try:
			self._chat_submission_handler(message.strip(), conversation_id)
		except Exception as error:
			logger.exception("HostRenderer chat submission handler failed")

	def chat_set_history(
		self,
		use_case_id: str | None,
		conversation_id: str,
		messages: list[dict[str, Any]],
		metadata: dict[str, Any] | None = None,
	) -> None:
		payload = {
			"use_case_id": use_case_id,
			"conversation_id": conversation_id,
			"messages": messages,
			"metadata": metadata,
		}
		self._send_command("chat_set_history", payload)

	def chat_append(
		self,
		use_case_id: str | None,
		conversation_id: str,
		message: dict[str, Any],
		metadata: dict[str, Any] | None = None,
	) -> None:
		payload = {
			"use_case_id": use_case_id,
			"conversation_id": conversation_id,
			"message": message,
			"metadata": metadata,
		}
		self._send_command("chat_append", payload)

	def chat_update(
		self,
		use_case_id: str | None,
		conversation_id: str,
		message_id: str,
		content: list[dict[str, Any]] | str,
		status: str | None = None,
		metadata: dict[str, Any] | None = None,
	) -> None:
		payload = {
			"use_case_id": use_case_id,
			"conversation_id": conversation_id,
			"message_id": message_id,
			"content": content,
			"status": status,
			"metadata": metadata,
		}
		self._send_command("chat_update", payload)

	def show_error(self, error_message: str, details: str | None = None) -> None:
		payload = {
			"error_message": error_message,
			"details": details,
		}
		self._send_command("show_error", payload)

	def show_progress(self, message: str) -> None:
		payload = {"stage": "progress", "message": message}
		self._send_command("update_progress", payload)

	def close_window(self, reason: str | None = None) -> None:
		payload = {"reason": reason}
		self._send_command("close_window", payload)

	def is_available(self) -> bool:
		logger.debug("HostRenderer is_available() probe starting")
		try:
			self._send_command("health_check", {})
			logger.debug("HostRenderer is_available() probe succeeded")
			return True
		except HostUnavailableError:
			logger.warning("HostRenderer is_available() probe failed")
			return False

	def _send_command(self, command_name: str, payload: dict[str, Any]) -> None:
		command = HostCommand(name=command_name, payload=payload)
		message = command.to_json() + "\n"
		print("ABOUT TO SEND COMMAND FROM HOST_RENDERER:", command_name, command.id)
		logger.debug("HostRenderer sending command name=%s message_id=%s payload=%s", command.name, command.id, payload)
		self._ensure_host_running()
		try:
			self._write_pipe(message.encode("utf-8"))
		except HostUnavailableError:
			raise
		except Exception as error:
			raise HostUnavailableError(str(error)) from error

	def _probe_host(self) -> None:
		command = HostCommand(name="health_check", payload={})
		message = command.to_json() + "\n"
		logger.debug("HostRenderer probing host with health_check message_id=%s", command.id)
		response_bytes = self._transport.send_and_receive(message.encode("utf-8"))
		self._process_response(response_bytes)
		logger.debug("HostRenderer host health_check succeeded message_id=%s", command.id)

	def _ensure_host_running(self) -> None:
		try:
			start_host_if_needed()
		except HostUnavailableError:
			raise
		if not self._host_ready:
			try:
				self._probe_host()
			except Exception as error:
				logger.error("HostRenderer host health check failed: %s", error, exc_info=True)
				raise HostUnavailableError(str(error)) from error
			self._host_ready = True

	def _write_pipe(self, message: bytes) -> None:
		logger.debug(
			"HostRenderer writing %d bytes to transport: %s",
			len(message),
			message[:200].decode('utf-8', errors='replace'),
		)
		print("STEP 4: CALLING transport.send")
		try:
			response_bytes = self._transport.send(message)
			logger.debug("HostRenderer received %d response bytes from transport", len(response_bytes))
			self._process_response(response_bytes)
			logger.debug("HostRenderer successfully wrote pipe message")
		except ImportError:
			logger.debug("HostRenderer win32 library unavailable, using fallback pipe writer")
			self._write_pipe_fallback(message)
		except TimeoutError as error:
			raise HostUnavailableError(str(error)) from error
		except Exception as error:
			winerror = getattr(error, "winerror", None)
			if winerror in (2, 231):
				logger.warning("HostRenderer pipe not ready yet (winerror=%s); retrying...", winerror, exc_info=True)
			logger.error("HostRenderer transport error: %s", error, exc_info=True)
			raise HostUnavailableError(str(error)) from error

	def _process_response(self, response_bytes: bytes) -> None:
		response_text = response_bytes.decode("utf-8", errors="replace").replace("\r", "").replace("\n", "").strip("\x00 ")
		if not response_text:
			logger.debug("HostRenderer received empty response payload")
			return

		try:
			logger.debug("HostRenderer response raw bytes: %r", response_bytes)
			logger.debug("HostRenderer response text: %s", response_text)
			response = HostResponse.from_json(response_text)
			if response.status == "nack":
				raise HostUnavailableError(response.message or "Host returned nack")
			logger.debug("HostRenderer received ACK response: %s stage=%s", response.request_id, response.stage)
		except ValueError as error:
			logger.warning("HostRenderer invalid response payload: %s; %s", response_text, error)
			return
		except Exception as error:
			logger.warning("HostRenderer response handling failed: %s", error)
			return

	def _write_pipe_fallback(self, message: bytes) -> None:
		try:
			with open(self.PIPE_NAME, "wb", buffering=0) as pipe:
				pipe.write(message)
		except OSError as error:
			raise HostUnavailableError(str(error)) from error
