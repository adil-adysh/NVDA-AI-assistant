# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
from typing import Any, Callable
from uuid import uuid4

from .host_interface import HostTransport, UIHostRenderer
from .host_lifecycle import HostLifecycleService
from .host_process import start_host_if_needed
from .host_protocol import (
	EVENT_CHAT_SUBMITTED,
	EVENT_MODEL_SELECTED,
	EVENT_PROVIDER_SELECTED,
	EVENT_THINK_MODE_TOGGLED,
	EVENT_UI_ACTION_INVOKED,
	HostCommand,
	HostEvent,
	HostResponse,
	HostUnavailableError,
)
from .host_transport import HostPipeTransport

logger = logging.getLogger(__name__)
HostCommandPayload = dict[str, Any]


class HostRenderer(UIHostRenderer):
	COMMAND_PIPE_NAME = r"\\.\pipe\nvda_ai_assistant_ui_cmd"
	EVENT_PIPE_NAME = r"\\.\pipe\nvda_ai_assistant_ui_evt"

	def __init__(self, lifecycle: HostLifecycleService | None = None) -> None:
		self._current_conversation_id: str | None = None
		self._current_use_case_id: str | None = None
		self._chat_submission_handler: Callable[[str, str | None, dict[str, Any] | None], None] | None = None
		self._ui_action_handler: Callable[[str, dict[str, Any] | None], None] | None = None
		self._provider_selection_handler: Callable[[str], None] | None = None
		self._model_selection_handler: Callable[[str | None, str], None] | None = None
		self._think_mode_handler: Callable[[bool], None] | None = None
		self._transport: HostTransport = HostPipeTransport(
			self.COMMAND_PIPE_NAME,
			event_pipe_name=self.EVENT_PIPE_NAME,
			event_callback=self._on_host_event,
		)
		self._lifecycle = lifecycle or HostLifecycleService()

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
		copy_markdown: str | None = None,
		metadata: dict[str, Any] | None = None,
	) -> None:
		logger.debug("HostRenderer.render_display_result called use_case_id=%s title=%s", use_case_id, title)
		payload: HostCommandPayload = {
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
			"copy_markdown": copy_markdown,
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
		payload: HostCommandPayload = {
			"use_case_id": use_case_id,
			"conversation_id": self._current_conversation_id,
			"title": title,
			"initial_text": initial_text,
			"initial_image_base64": initial_image_base64,
			"metadata": metadata,
		}
		self._send_command("open_chat", payload)

	def sync_session_state(self, metadata: dict[str, Any] | None = None) -> None:
		metadata_conversation_id = metadata.get("conversation_id") if isinstance(metadata, dict) else None
		if isinstance(metadata_conversation_id, str) and metadata_conversation_id.strip():
			self._current_conversation_id = metadata_conversation_id.strip()
		payload: HostCommandPayload = {
			"conversation_id": self._current_conversation_id,
			"metadata": metadata,
		}
		self._send_command("sync_session", payload)

	def register_chat_submission_handler(self, handler: Callable[[str, str | None, dict[str, Any] | None], None]) -> None:
		self._chat_submission_handler = handler

	def register_ui_action_handler(self, handler: Callable[[str, dict[str, Any] | None], None]) -> None:
		self._ui_action_handler = handler

	def register_provider_selection_handler(self, handler: Callable[[str], None]) -> None:
		self._provider_selection_handler = handler

	def register_model_selection_handler(self, handler: Callable[[str | None, str], None]) -> None:
		self._model_selection_handler = handler

	def register_think_mode_handler(self, handler: Callable[[bool], None]) -> None:
		self._think_mode_handler = handler

	def _on_host_event(self, event: HostEvent) -> None:
		if event.event == EVENT_CHAT_SUBMITTED:
			message = event.payload.get("message")
			conversation_id = event.payload.get("conversation_id") or self._current_conversation_id
			if message is None:
				message = ""
			if not isinstance(message, str):
				logger.warning("Received chat_submitted event with a non-string message")
				return

			if self._chat_submission_handler is None:
				logger.warning("HostRenderer has no chat submission handler registered")
				return

			try:
				self._chat_submission_handler(message.strip(), conversation_id, event.payload)
			except Exception:
				logger.exception("HostRenderer chat submission handler failed")
			return

		if event.event == EVENT_UI_ACTION_INVOKED:
			action_id = event.payload.get("action_id")
			payload = event.payload.get("payload")
			if not isinstance(action_id, str) or not action_id.strip():
				logger.warning("Received ui_action_invoked without an action id")
				return
			if self._ui_action_handler is None:
				logger.debug("HostRenderer has no UI action handler registered")
				return
			try:
				self._ui_action_handler(action_id, payload if isinstance(payload, dict) else None)
			except Exception:
				logger.exception("HostRenderer UI action handler failed")
			return

		if event.event == EVENT_PROVIDER_SELECTED:
			provider = event.payload.get("provider")
			if not isinstance(provider, str) or not provider.strip():
				logger.warning("Received provider_selected without a provider")
				return
			if self._provider_selection_handler is None:
				logger.debug("HostRenderer has no provider selection handler registered")
				return
			try:
				self._provider_selection_handler(provider.strip())
			except Exception:
				logger.exception("HostRenderer provider selection handler failed")
			return

		if event.event == EVENT_MODEL_SELECTED:
			model = event.payload.get("model")
			provider = event.payload.get("provider")
			if not isinstance(model, str) or not model.strip():
				logger.warning("Received model_selected without a model")
				return
			if self._model_selection_handler is None:
				logger.debug("HostRenderer has no model selection handler registered")
				return
			try:
				self._model_selection_handler(provider if isinstance(provider, str) else None, model.strip())
			except Exception:
				logger.exception("HostRenderer model selection handler failed")
			return

		if event.event == EVENT_THINK_MODE_TOGGLED:
			enabled = event.payload.get("enabled")
			if not isinstance(enabled, bool):
				logger.warning("Received think_mode_toggled without a boolean enabled flag")
				return
			if self._think_mode_handler is None:
				logger.debug("HostRenderer has no think mode handler registered")
				return
			try:
				self._think_mode_handler(enabled)
			except Exception:
				logger.exception("HostRenderer think mode handler failed")
			return

		logger.debug("HostRenderer received unsupported host event: %s", event.event)

	def chat_set_history(
		self,
		use_case_id: str | None,
		conversation_id: str,
		messages: list[dict[str, Any]],
		metadata: dict[str, Any] | None = None,
	) -> None:
		if conversation_id.strip():
			self._current_conversation_id = conversation_id.strip()
		payload: HostCommandPayload = {
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
		if conversation_id.strip():
			self._current_conversation_id = conversation_id.strip()
		payload: HostCommandPayload = {
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
		if conversation_id.strip():
			self._current_conversation_id = conversation_id.strip()
		payload: HostCommandPayload = {
			"use_case_id": use_case_id,
			"conversation_id": conversation_id,
			"message_id": message_id,
			"content": content,
			"status": status,
			"metadata": metadata,
		}
		self._send_command("chat_update", payload)

	def chat_stream_begin(
		self,
		use_case_id: str | None,
		conversation_id: str,
		message_id: str,
		role: str = "assistant",
		metadata: dict[str, Any] | None = None,
	) -> None:
		if conversation_id.strip():
			self._current_conversation_id = conversation_id.strip()
		payload: HostCommandPayload = {
			"use_case_id": use_case_id,
			"conversation_id": conversation_id,
			"message_id": message_id,
			"role": role,
			"metadata": metadata,
		}
		self._send_command("chat_stream_begin", payload)

	def chat_stream_delta(
		self,
		use_case_id: str | None,
		conversation_id: str,
		message_id: str,
		delta: str,
		sequence: int,
		metadata: dict[str, Any] | None = None,
	) -> None:
		if conversation_id.strip():
			self._current_conversation_id = conversation_id.strip()
		payload: HostCommandPayload = {
			"use_case_id": use_case_id,
			"conversation_id": conversation_id,
			"message_id": message_id,
			"delta": delta,
			"sequence": sequence,
			"metadata": metadata,
		}
		self._send_command("chat_stream_delta", payload)

	def chat_stream_end(
		self,
		use_case_id: str | None,
		conversation_id: str,
		message_id: str,
		content: list[dict[str, Any]] | str,
		status: str | None = None,
		metadata: dict[str, Any] | None = None,
	) -> None:
		if conversation_id.strip():
			self._current_conversation_id = conversation_id.strip()
		payload: HostCommandPayload = {
			"use_case_id": use_case_id,
			"conversation_id": conversation_id,
			"message_id": message_id,
			"content": content,
			"status": status,
			"metadata": metadata,
		}
		self._send_command("chat_stream_end", payload)

	def chat_stream_abort(
		self,
		use_case_id: str | None,
		conversation_id: str,
		message_id: str,
		reason: str | None = None,
		metadata: dict[str, Any] | None = None,
	) -> None:
		if conversation_id.strip():
			self._current_conversation_id = conversation_id.strip()
		payload: HostCommandPayload = {
			"use_case_id": use_case_id,
			"conversation_id": conversation_id,
			"message_id": message_id,
			"reason": reason,
			"metadata": metadata,
		}
		self._send_command("chat_stream_abort", payload)

	def show_error(self, error_message: str, details: str | None = None) -> None:
		payload: HostCommandPayload = {
			"error_message": error_message,
			"details": details,
		}
		self._send_command("show_error", payload)

	def show_progress(self, message: str) -> None:
		payload: HostCommandPayload = {"stage": "progress", "message": message}
		self._send_command("update_progress", payload)

	def close_window(self, reason: str | None = None) -> None:
		payload: HostCommandPayload = {"reason": reason}
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

	def _send_command(self, command_name: str, payload: HostCommandPayload) -> None:
		command = HostCommand(name=command_name, payload=payload)
		message = command.to_bytes()
		logger.debug("HostRenderer sending command name=%s message_id=%s payload=%s", command.name, command.id, payload)
		self._ensure_host_running()
		try:
			response_bytes = self._transport.send(message)
			self._process_response(response_bytes)
			self._lifecycle.mark_command_succeeded(command_name)
		except HostUnavailableError:
			self._lifecycle.mark_failed()
			raise
		except Exception as error:
			self._lifecycle.mark_failed()
			raise HostUnavailableError(str(error)) from error

	def _probe_host(self) -> None:
		command = HostCommand(name="health_check", payload={})
		logger.debug("HostRenderer probing host with health_check message_id=%s", command.id)
		response_bytes = self._transport.send(command.to_bytes())
		self._process_response(response_bytes)
		logger.debug("HostRenderer host health_check succeeded message_id=%s", command.id)

	def _ensure_host_running(self) -> None:
		try:
			self._lifecycle.ensure_started(start_host_if_needed)
		except HostUnavailableError:
			raise
		start_event_listener = getattr(self._transport, "start_event_listener", None)
		if callable(start_event_listener):
			start_event_listener()
		if self._lifecycle.state.name not in {"READY", "HIDDEN"}:
			try:
				self._probe_host()
			except Exception as error:
				logger.error("HostRenderer host health check failed: %s", error, exc_info=True)
				self._lifecycle.mark_failed()
				raise HostUnavailableError(str(error)) from error
			self._lifecycle.mark_ready()

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
		except HostUnavailableError:
			self._lifecycle.mark_failed()
			raise
		except ValueError as error:
			logger.warning("HostRenderer invalid response payload: %s; %s", response_text, error)
			return
		except Exception as error:
			self._lifecycle.mark_failed()
			logger.warning("HostRenderer response handling failed: %s", error)
			raise HostUnavailableError(str(error)) from error

	def _write_pipe_fallback(self, message: bytes) -> None:
		try:
			with open(self.PIPE_NAME, "wb", buffering=0) as pipe:
				pipe.write(message)
		except OSError as error:
			raise HostUnavailableError(str(error)) from error
