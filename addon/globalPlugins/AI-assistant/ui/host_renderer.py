# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
from typing import Any

from .host_interface import UIHostRenderer

logger = logging.getLogger(__name__)
from .host_process import start_host_if_needed
from .host_protocol import HostCommand, HostResponse, HostUnavailableError
from .host_transport import HostPipeTransport


class HostRenderer(UIHostRenderer):
	PIPE_NAME = r"\\.\pipe\nvda_ai_assistant_ui"

	def __init__(self) -> None:
		self._transport = HostPipeTransport(self.PIPE_NAME)

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
		metadata: dict[str, Any] | None = None,
	) -> None:
		payload = {
			"use_case_id": use_case_id,
			"title": title,
			"initial_text": initial_text,
			"initial_image_base64": initial_image_base64,
			"metadata": metadata,
		}
		self._send_command("open_chat", payload)

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
		try:
			self._send_command("health_check", {})
			return True
		except HostUnavailableError:
			return False

	def _send_command(self, command_name: str, payload: dict[str, Any]) -> None:
		command = HostCommand(name=command_name, payload=payload)
		message = command.to_json() + "\n"
		logger.debug("HostRenderer sending command name=%s message_id=%s payload=%s", command.name, command.id, payload)
		self._ensure_host_running()
		try:
			self._write_pipe(message.encode("utf-8"))
		except HostUnavailableError:
			raise
		except Exception as error:
			raise HostUnavailableError(str(error)) from error

	def _ensure_host_running(self) -> None:
		try:
			start_host_if_needed()
		except HostUnavailableError:
			raise

	def _write_pipe(self, message: bytes) -> None:
		try:
			response_bytes = self._transport.send_and_receive(message)
			logger.debug("HostRenderer received %d response bytes from transport", len(response_bytes))
			self._process_response(response_bytes)
		except ImportError:
			logger.debug("HostRenderer win32 library unavailable, using fallback pipe writer")
			self._write_pipe_fallback(message)
		except TimeoutError as error:
			raise HostUnavailableError(str(error)) from error
		except Exception as error:
			winerror = getattr(error, "winerror", None)
			if winerror in (2, 231):
				logger.warning("HostRenderer pipe not ready yet (winerror=%s); retrying...", winerror, exc_info=True)
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
