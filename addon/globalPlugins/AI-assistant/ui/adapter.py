# -*- coding: utf-8 -*-
from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from typing import Any

from logHandler import log
from . import nvda_ui
from .host_renderer import HostRenderer, HostUnavailableError
from .native_renderer import NativeRenderer


class UIAdapter:
	def __init__(self) -> None:
		self._native_renderer = NativeRenderer()
		self._host_renderer = HostRenderer()
		self._host_available = True
		self._command_queue: queue.Queue[tuple[Callable[[], None], Callable[[], None]]] = queue.Queue()
		self._running = True
		self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
		self._worker_thread.start()

	def _worker_loop(self) -> None:
		log.debug("UIAdapter worker thread started")
		while self._running:
			try:
				command, fallback = self._command_queue.get(block=True)
				log.debug("UIAdapter dequeued command %s", command)
				log.debug("QUEUE ID (worker): %s", id(self._command_queue))
				try:
					log.debug("UIAdapter worker invoking command")
					command()
					log.debug("UIAdapter worker command executed successfully")
				except HostUnavailableError:
					log.warning("WORKER ERROR: HostUnavailableError")
					log.warning("UIAdapter host command failed because host is unavailable")
					self._host_available = False
					nvda_ui.queue(fallback)
				except Exception as error:
					log.warning("WORKER ERROR: %s", error)
					log.exception("UIAdapter host command threw unexpected exception")
					self._host_available = False
					nvda_ui.queue(fallback)
				finally:
					self._command_queue.task_done()
			except Exception as error:
				log.warning("WORKER ERROR: %s", error)
				raise

	def _dispatch_host_command(self, command: Callable[[], None], fallback: Callable[[], None]) -> None:
		log.debug("ENQUEUE COMMAND: %s", command)
		log.debug("QUEUE ID (enqueue): %s", id(self._command_queue))
		log.debug("UIAdapter dispatching host command; host_available=%s", self._host_available)
		self._command_queue.put((command, fallback))

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
		if self._host_available:
			self._dispatch_host_command(
				lambda: self._host_renderer.render_display_result(
					use_case_id=use_case_id,
					title=title,
					output_text=output_text,
					output_html=output_html,
					is_html=is_html,
					success=success,
					message=message,
					close_button=close_button,
					copy_button=copy_button,
					copy_text=copy_text,
					copy_html=copy_html,
					metadata=metadata,
				),
				lambda: self._native_renderer.render_display_result(
					use_case_id=use_case_id,
					title=title,
					output_text=output_text,
					output_html=output_html,
					is_html=is_html,
					success=success,
					message=message,
					close_button=close_button,
					copy_button=copy_button,
					copy_text=copy_text,
					copy_html=copy_html,
					metadata=metadata,
				),
			)
			return

		self._native_renderer.render_display_result(
			use_case_id=use_case_id,
			title=title,
			output_text=output_text,
			output_html=output_html,
			is_html=is_html,
			success=success,
			message=message,
			close_button=close_button,
			copy_button=copy_button,
			copy_text=copy_text,
			copy_html=copy_html,
			metadata=metadata,
		)

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
		if self._host_available:
			if coordinator is not None:
				def handle_chat_submission(message: str, conversation_id: str | None) -> None:
					threading.Thread(
						target=self._handle_host_chat_submission,
						args=(message, conversation_id, coordinator),
						daemon=True,
					).start()
				self._host_renderer.register_chat_submission_handler(handle_chat_submission)

			self._dispatch_host_command(
				lambda: self._host_renderer.open_chat(
					use_case_id=use_case_id,
					title=title,
					initial_text=initial_text,
					initial_image_base64=initial_image_base64,
					coordinator=coordinator,
					tool_registry=tool_registry,
					metadata=metadata,
				),
				lambda: self._native_renderer.open_chat(
					use_case_id=use_case_id,
					title=title,
					initial_text=initial_text,
					initial_image_base64=initial_image_base64,
					coordinator=coordinator,
					tool_registry=tool_registry,
					metadata=metadata,
				),
			)
			return

		self._native_renderer.open_chat(
			use_case_id=use_case_id,
			title=title,
			initial_text=initial_text,
			initial_image_base64=initial_image_base64,
			coordinator=coordinator,
			tool_registry=tool_registry,
			metadata=metadata,
		)

	def _handle_host_chat_submission(self, message: str, conversation_id: str | None, coordinator: Any) -> None:
		conversation_id = conversation_id or None
		use_case_id = None
		# Append the user message to the UI immediately.
		self._host_renderer.chat_append(
			use_case_id,
			conversation_id or "",
			{
				"id": f"user-{message[:8]}",
				"role": "user",
				"content": [{"type": "text", "text": message}],
			},
		)
		try:
			response = coordinator.send_message(text=message)
			assistant_text = getattr(response, "text", None)
			if isinstance(assistant_text, str) and assistant_text.strip():
				self._host_renderer.chat_append(
					use_case_id,
					conversation_id or "",
					{
						"id": f"assistant-{message[:8]}",
						"role": "assistant",
						"content": [{"type": "text", "text": assistant_text.strip()}],
					},
				)
		except Exception as error:
			self._host_renderer.show_error("Chat submission failed", details=str(error))

	def show_error(self, error_message: str, details: str | None = None) -> None:
		if self._host_available:
			self._dispatch_host_command(
				lambda: self._host_renderer.show_error(error_message, details=details),
				lambda: self._native_renderer.show_error(error_message, details=details),
			)
			return

		self._native_renderer.show_error(error_message, details=details)

	def show_progress(self, message: str) -> None:
		if self._host_available:
			self._dispatch_host_command(
				lambda: self._host_renderer.show_progress(message),
				lambda: self._native_renderer.show_progress(message),
			)
			return

		self._native_renderer.show_progress(message)

	def close_window(self, reason: str | None = None) -> None:
		if self._host_available:
			self._dispatch_host_command(
				lambda: self._host_renderer.close_window(reason),
				lambda: self._native_renderer.close_window(reason),
			)
			return

		self._native_renderer.close_window(reason)


ui_adapter = UIAdapter()
