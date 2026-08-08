# -*- coding: utf-8 -*-
from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from logHandler import log

from ..plugin.background import ensure_litert_server_ready
from ..providers.runtime.server import LiteRTServerError
from ..service.error_presentation import ErrorPresentation, present_error
from ..service.provider_controls import provider_control_service
from .host_lifecycle import HostLifecycleService, HostLifecycleState
from .intent import ATTENTION_POLICY_FOREGROUND_IF_BACKGROUND, merge_presentation_intent
from . import nvda_ui
from .accessibility import queue_response_announcement, strip_html_for_announcement
from .host_renderer import HostRenderer, HostUnavailableError
from .attachment_context import extract_attachment_context
from .view_models import ChatWindowViewModel, DisplayResultViewModel
from .stream_projection import StreamProjection
from ..utils.markdown import render_markdown_to_html


class UIAdapter:
	def __init__(self) -> None:
		self._host_lifecycle = HostLifecycleService()
		self._host_renderer = HostRenderer(lifecycle=self._host_lifecycle)
		self._host_renderer.register_host_closed_handler(self._handle_host_closed)
		self._result_action_handler: Callable[[str, dict[str, Any] | None], None] | None = None
		self._session_metadata_provider: Callable[[], dict[str, Any]] | None = None
		self._pending_session_metadata: dict[str, Any] | None = None
		self._command_queue: queue.Queue[tuple[Callable[[], None], Callable[[], None]]] = queue.Queue()
		self._running = True
		self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
		self._worker_thread.start()

	def register_result_action_handler(self, handler: Callable[[str, dict[str, Any] | None], None]) -> None:
		self._result_action_handler = handler

	def register_session_metadata_provider(self, provider: Callable[[], dict[str, Any]]) -> None:
		self._session_metadata_provider = provider

	def close(self) -> None:
		try:
			close_host = getattr(self._host_renderer, "close", None)
			if callable(close_host):
				close_host()
		except Exception:
			log.exception("UIAdapter host cleanup failed")
		finally:
			self._running = False

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
					self._mark_host_unavailable()
					nvda_ui.queue(fallback)
				except Exception as error:
					log.warning("WORKER ERROR: %s", error)
					log.exception("UIAdapter host command threw unexpected exception")
					self._mark_host_unavailable()
					nvda_ui.queue(fallback)
				finally:
					self._command_queue.task_done()
			except Exception as error:
				log.warning("WORKER ERROR: %s", error)
				raise

	def _dispatch_host_command(self, command: Callable[[], None], fallback: Callable[[], None]) -> None:
		log.debug("ENQUEUE COMMAND: %s", command)
		log.debug("QUEUE ID (enqueue): %s", id(self._command_queue))
		log.debug("UIAdapter dispatching host command; host_state=%s", self._host_lifecycle.state)
		self._command_queue.put((command, fallback))

	def _dispatch_primary_host_command(self, command: Callable[[], None], fallback: Callable[[], None]) -> None:
		if self._host_lifecycle.state == HostLifecycleState.FAILED:
			log.info("UIAdapter retrying WebView host for a primary UI action")
		self._host_lifecycle.prepare_primary_action()

		def command_with_session_sync() -> None:
			command()
			self._flush_pending_session_state()

		self._dispatch_host_command(command_with_session_sync, fallback)

	def _mark_host_unavailable(self) -> None:
		self._host_lifecycle.mark_failed()

	def _notify_host_unavailable(self) -> None:
		message = self._get_localized_strings().get("host_unavailable_message", "AI WebView host is unavailable.")
		nvda_ui.message(message)

	def render_display(self, view_model: DisplayResultViewModel) -> None:
		metadata = view_model.transport_metadata()
		self._remember_session_metadata(metadata)
		self._host_renderer.register_ui_action_handler(self._handle_host_ui_action)
		if view_model.success:
			queue_response_announcement(
				nvda_ui.queue,
				nvda_ui.message,
				view_model.output_text,
				strip_html_for_announcement(view_model.output_html),
			)
		self._dispatch_primary_host_command(
			lambda: self._host_renderer.render_display_result(
				use_case_id=view_model.use_case_id,
				title=view_model.title,
				output_text=view_model.output_text,
				output_html=view_model.output_html,
				is_html=view_model.is_html,
				success=view_model.success,
				message=view_model.message,
				close_button=view_model.close_button,
				copy_button=view_model.copy_button,
				copy_text=view_model.copy_text,
				copy_markdown=view_model.copy_markdown,
				metadata=metadata,
			),
			self._notify_host_unavailable,
		)

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
		self.render_display(
			DisplayResultViewModel(
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
				copy_markdown=copy_markdown,
				metadata=dict(metadata or {}),
			)
		)

	def open_chat_view(
		self,
		view_model: ChatWindowViewModel,
		coordinator: Any | None = None,
		tool_registry: Any | None = None,
		history_messages: list[dict[str, Any]] | None = None,
	) -> None:
		metadata = dict(view_model.metadata)
		conversation_id = metadata.get("conversation_id") if isinstance(metadata.get("conversation_id"), str) else None
		self._remember_session_metadata(metadata)

		# When the host was previously shown and is now hidden (not restarted),
		# the WebView still has the conversation loaded. Tell the WebView to
		# preserve the existing transcript and skip re-sending history.
		is_hidden = self._host_lifecycle.state == HostLifecycleState.HIDDEN
		if is_hidden:
			metadata = {**metadata, "preserve_conversation": True}

		if coordinator is not None:
			def handle_chat_submission(message: str, conversation_id: str | None, event_payload: dict[str, Any] | None) -> None:
				threading.Thread(
					target=self._handle_host_chat_submission,
					args=(message, conversation_id, coordinator, event_payload),
					daemon=True,
				).start()
			self._host_renderer.register_chat_submission_handler(handle_chat_submission)
		self._host_renderer.register_ui_action_handler(self._handle_host_ui_action)
		self._host_renderer.register_provider_selection_handler(self._handle_provider_selection)
		self._host_renderer.register_model_selection_handler(self._handle_model_selection)
		self._host_renderer.register_think_mode_handler(self._handle_think_mode_toggle)

		self._dispatch_primary_host_command(
			lambda: self._host_renderer.open_chat(
				use_case_id=view_model.use_case_id,
				title=view_model.title,
				initial_text=view_model.initial_text,
				initial_image_base64=view_model.initial_image_base64,
				coordinator=coordinator,
				tool_registry=tool_registry,
				metadata=metadata,
			),
			self._notify_host_unavailable,
		)
		if history_messages and conversation_id and not is_hidden:
			self._dispatch_host_command(
				lambda conv_id=conversation_id: self._host_renderer.chat_set_history(
					view_model.use_case_id,
					conv_id,
					history_messages,
					metadata=metadata,
				),
				lambda: None,
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
		self.open_chat_view(
			ChatWindowViewModel(
				use_case_id=use_case_id,
				title=title,
				initial_text=initial_text,
				initial_image_base64=initial_image_base64,
				metadata=dict(metadata or {}),
			),
			coordinator=coordinator,
			tool_registry=tool_registry,
		)

	def sync_session_state(self, metadata: dict[str, Any] | None = None) -> None:
		self._remember_session_metadata(metadata)
		if not self._host_lifecycle.should_dispatch_background_command():
			return
		self._dispatch_host_command(
			lambda: self._send_session_state(metadata),
			lambda: None,
		)

	def _remember_session_metadata(self, metadata: dict[str, Any] | None) -> None:
		if isinstance(metadata, dict):
			self._pending_session_metadata = dict(metadata)

	def _final_answer_metadata(self, metadata: dict[str, Any] | None = None) -> dict[str, object]:
		return merge_presentation_intent(
			metadata,
			attention_policy=ATTENTION_POLICY_FOREGROUND_IF_BACKGROUND,
		)

	def _send_session_state(self, metadata: dict[str, Any] | None = None) -> None:
		effective_metadata = metadata if isinstance(metadata, dict) else self._pending_session_metadata
		self._host_renderer.sync_session_state(metadata=effective_metadata)
		if effective_metadata is not None:
			self._pending_session_metadata = None

	def _flush_pending_session_state(self) -> None:
		if self._pending_session_metadata is None:
			return
		self._send_session_state()

	def _handle_host_chat_submission(
		self,
		message: str,
		conversation_id: str | None,
		coordinator: Any,
		event_payload: dict[str, Any] | None = None,
	) -> None:
		conversation_id = conversation_id or None
		use_case_id = None
		localized_strings = self._get_localized_strings()
		image_base64, file_context = self._extract_attachment_context(event_payload, localized_strings)
		message_text = message
		if file_context:
			message_text = f"{message_text}\n\n{file_context}".strip()
		if not message_text and image_base64 is None:
			return

		user_content = self._build_user_content(message_text, image_base64, localized_strings)
		self._host_renderer.chat_append(
			use_case_id,
			conversation_id or "",
			{
				"id": self._new_message_id("user"),
				"role": "user",
				"content": user_content,
			},
		)
		assistant_projection = StreamProjection(
			renderer=self._host_renderer,
			use_case_id=use_case_id,
			conversation_id=conversation_id or "",
			message_id=self._new_message_id("assistant"),
			stream_id=str(uuid4()),
			final_metadata_factory=self._final_answer_metadata,
		)

		try:
			ensure_litert_server_ready(
				on_progress=lambda msg: nvda_ui.queue(nvda_ui.message, msg),
			)
			response = coordinator.send_message(
				text=message_text or None,
				image_base64=image_base64,
				progress_callback=assistant_projection.update,
			)
			assistant_text = getattr(response, "text", None)
			thinking_trace = self._extract_thinking_trace(response)
			if isinstance(assistant_text, str) and assistant_text.strip():
				assistant_content = self._build_assistant_content_blocks(
					assistant_text,
					localized_strings,
					thinking_trace=thinking_trace if isinstance(thinking_trace, str) else None,
				)
				assistant_projection.finish(assistant_content)
				queue_response_announcement(nvda_ui.queue, nvda_ui.message, assistant_text)
		except LiteRTServerError as error:
			presentation = present_error(error)
			assistant_projection.abort(reason=presentation.message)
			error_content = self._build_error_content_blocks(presentation, localized_strings)
			error_metadata = dict(assistant_projection.final_metadata_factory())
			if message_text:
				error_metadata["restore_text"] = message_text
			self._host_renderer.chat_append(
				use_case_id,
				conversation_id or "",
				{
					"id": assistant_projection.message_id,
					"role": "assistant",
					"content": error_content,
				},
				metadata=error_metadata,
			)
			nvda_ui.message(presentation.message)
		except Exception as error:
			presentation = present_error(error)
			# ── Clean up streaming state if it had started ──
			assistant_projection.abort(reason=presentation.message)
			# ── Append error as an assistant message in the transcript ──
			#     The metadata carries restore_text so the WebView can restore
			#     the user's message in the composer for retry.
			error_content = self._build_error_content_blocks(presentation, localized_strings)
			error_metadata = dict(assistant_projection.final_metadata_factory())
			if message_text:
				error_metadata["restore_text"] = message_text
			self._host_renderer.chat_append(
				use_case_id,
				conversation_id or "",
				{
					"id": assistant_projection.message_id,
					"role": "assistant",
					"content": error_content,
				},
				metadata=error_metadata,
			)
			nvda_ui.message(presentation.message)

	def _build_user_content(
		self,
		message_text: str,
		image_base64: str | None,
		localized_strings: dict[str, str],
	) -> list[dict[str, Any]]:
		content: list[dict[str, Any]] = []
		if message_text:
			content.append({"type": "text", "text": message_text})
		if image_base64:
			content.append(
				{
					"type": "image",
					"image_base64": image_base64,
					"mime_type": "image/png",
					"alt": localized_strings.get("image_attachment_notice", "[Image attachment included]"),
				}
			)
		return content

	def _build_assistant_content_blocks(
		self,
		assistant_text: str,
		localized_strings: dict[str, str],
		thinking_trace: str | None = None,
	) -> list[dict[str, Any]]:
		content: list[dict[str, Any]] = []
		normalized_text = assistant_text.strip()
		if normalized_text:
			rendered_html = render_markdown_to_html(normalized_text).strip()
			if rendered_html:
				content.append({"type": "html", "html": rendered_html})
			else:
				content.append({"type": "text", "text": normalized_text})
		if isinstance(thinking_trace, str) and thinking_trace.strip():
			content.append(
				{
					"type": "thinking",
					"text": thinking_trace.strip(),
					"summary": localized_strings.get("thinking_trace_label", "Thinking trace"),
					"collapsed": True,
				}
			)
		return content

	def _build_error_content_blocks(
		self,
		presentation: ErrorPresentation,
		localized_strings: dict[str, str],
	) -> list[dict[str, Any]]:
		"""Build a content block list that renders as an inline error message in the chat transcript."""
		content: list[dict[str, Any]] = []
		error_label = localized_strings.get("error_prefix", "Error")
		error_summary = "{0}: {1}".format(error_label, presentation.title) if presentation.title else error_label
		content.append(
			{
				"type": "error",
				"text": presentation.message,
				"summary": error_summary,
				"is_internal": presentation.is_internal,
			}
		)
		return content

	def _extract_thinking_trace(self, response: Any) -> str | None:
		raw = getattr(response, "raw", None)
		if raw is None:
			return None
		metadata = getattr(raw, "metadata", None)
		if isinstance(metadata, dict):
			thinking_trace = metadata.get("thinking_trace")
			return thinking_trace if isinstance(thinking_trace, str) else None
		return None

	def _extract_attachment_context(
		self,
		event_payload: dict[str, Any] | None,
		localized_strings: dict[str, str],
	) -> tuple[str | None, str]:
		attachments = event_payload.get("attachments") if isinstance(event_payload, dict) else None
		attached_file_label = localized_strings.get("attached_file_label", "Attached file")
		context = extract_attachment_context(attachments, attached_file_label=attached_file_label)
		if context.image_count > 1:
			log.warning("UIAdapter received %s image attachments; only the first supported image will be sent", context.image_count)
		return context.image_base64, context.file_context

	def _handle_host_ui_action(self, action_id: str, payload: dict[str, Any] | None) -> None:
		if self._result_action_handler is None:
			log.debug("UIAdapter received host UI action without a registered handler: %s", action_id)
			return
		try:
			self._result_action_handler(action_id, payload)
		except Exception:
			log.exception("UIAdapter result action handler failed")

	def _handle_host_closed(self, event_payload: dict[str, Any] | None) -> None:
		log.info("UIAdapter received host_closed event from host: %s", event_payload)
		self._host_lifecycle.mark_host_closed()

	def _handle_provider_selection(self, provider: str) -> None:
		self._apply_control_change(lambda: self._set_provider_and_save(provider))

	def _handle_model_selection(self, provider: str | None, model: str) -> None:
		self._apply_control_change(lambda: self._set_model_and_save(provider, model))

	def _handle_think_mode_toggle(self, enabled: bool) -> None:
		self._apply_control_change(lambda: self._set_think_mode_and_save(enabled))

	def _set_provider_and_save(self, provider: str) -> None:
		provider_control_service.select_provider(provider)

	def _set_model_and_save(self, provider: str | None, model: str) -> None:
		provider_control_service.select_model(model=model, provider=provider)

	def _set_think_mode_and_save(self, enabled: bool) -> None:
		provider_control_service.set_think_mode(enabled)

	def _apply_control_change(self, operation: Callable[[], None]) -> None:
		try:
			operation()
		except Exception as error:
			log.exception("UIAdapter control update failed")
			presentation = present_error(error)
			nvda_ui.message(presentation.message)
			self.sync_session_state(metadata=self._build_status_sync_metadata(presentation.message))

	def _build_status_sync_metadata(self, status_message: str) -> dict[str, Any] | None:
		metadata = dict(self._build_sync_metadata() or {})
		metadata["status_message"] = status_message
		return metadata

	def _build_sync_metadata(self) -> dict[str, Any] | None:
		if self._session_metadata_provider is None:
			return None
		return self._session_metadata_provider()

	def _get_localized_strings(self) -> dict[str, str]:
		metadata = self._build_sync_metadata() or {}
		localized_strings = metadata.get("localized_strings")
		if isinstance(localized_strings, dict):
			return {str(key): str(value) for key, value in localized_strings.items()}
		return {}

	def _new_message_id(self, prefix: str) -> str:
		return f"{prefix}-{uuid4().hex}"

	def show_error(self, error_message: str, details: str | None = None) -> None:
		if self._host_lifecycle.should_dispatch_background_command():
			self._dispatch_host_command(
				lambda: self._host_renderer.show_error(error_message, details=details),
				lambda: nvda_ui.message(error_message),
			)
			return

		nvda_ui.message(error_message)

	def show_progress(self, message: str) -> None:
		nvda_ui.queue(nvda_ui.message, message)
		if self._host_lifecycle.should_dispatch_background_command():
			self._dispatch_host_command(
				lambda: self._host_renderer.show_progress(message),
				lambda: None,
			)

	def close_window(self, reason: str | None = None) -> None:
		if self._host_lifecycle.should_dispatch_background_command():
			self._dispatch_host_command(
				lambda: self._host_renderer.close_window(reason),
				lambda: None,
			)
			return

		return


ui_adapter = UIAdapter()
