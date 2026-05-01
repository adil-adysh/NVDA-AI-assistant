# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from __future__ import annotations

import builtins
from collections.abc import Callable
from typing import Any, cast
from uuid import uuid4

import gui
from logHandler import log

from ..config.state import ProviderState
from ..core.events import ProgressEvent
from ..service.chat import ChatCoordinator
from ..tools import ToolRegistry
from ..config.settings import get_provider_state
from ..ui.adapter import ui_adapter
from ..ui.action_store import ResultActionStore
from ..ui import nvda_ui
from ..ui.session_state import build_session_state, merge_session_metadata
from ..ui.view_models import ChatWindowViewModel, DisplayResultViewModel, ResultActionViewModel


def _translate(message: str) -> str:
	return message


_ = cast(Callable[[str], str], getattr(builtins, "_", _translate))


class UseCasePresenter:
	def __init__(self, chat_coordinator: ChatCoordinator, tool_registry: ToolRegistry) -> None:
		self._chat_coordinator = chat_coordinator
		self._tool_registry = tool_registry
		self._active_conversation_id: str | None = None
		self._result_action_store = ResultActionStore()
		ui_adapter.register_result_action_handler(self._handle_result_action)
		ui_adapter.register_session_metadata_provider(self._build_chat_metadata)

	def open_chat_window(
		self,
		initial_text: str | None = None,
		initial_image_base64: str | None = None,
	) -> None:
		self._active_conversation_id = str(uuid4())
		session_state = build_session_state(_, conversation_id=self._active_conversation_id)
		ui_adapter.open_chat_view(
			ChatWindowViewModel(
				use_case_id=None,
				title=_("AI Chat"),
				initial_text=initial_text,
				initial_image_base64=initial_image_base64,
				metadata=session_state.to_metadata(),
			),
			coordinator=self._chat_coordinator,
			tool_registry=self._tool_registry,
		)

	def update_provider_state(self, provider_state: ProviderState | None = None) -> None:
		try:
			if provider_state is None:
				provider_state = get_provider_state()
			ui_adapter.sync_session_state(
				build_session_state(_, provider_state, conversation_id=self._active_conversation_id).to_metadata()
			)
		except Exception:
			log.exception("Error synchronizing WebView session state after provider change")

	def present_use_case_result(self, use_case_result: Any, title: str) -> None:
		log.debug("UseCasePresenter.present_use_case_result called title=%s result_type=%s", title, type(use_case_result).__name__)
		output_text = None
		output_html = None
		is_html = False

		if isinstance(use_case_result, dict):
			output_text = use_case_result.get("output_text")
			output_html = use_case_result.get("output_html")
			is_html = bool(use_case_result.get("is_html"))
		else:
			metadata = getattr(use_case_result, "metadata", None)
			output_text = getattr(use_case_result, "output_text", None)
			output_html = getattr(use_case_result, "output_html", None)
			if output_html is None and isinstance(metadata, dict):
				output_text = output_text or metadata.get("output_text")
				is_html = bool(getattr(use_case_result, "is_browseable", False) or metadata.get("is_html"))
			else:
				is_html = bool(getattr(use_case_result, "is_browseable", False))

		if isinstance(output_html, str) and output_html.strip():
			is_html = True

		has_output_text = isinstance(output_text, str) and bool(output_text.strip())
		has_output_html = isinstance(output_html, str) and bool(output_html.strip())

		if not has_output_text and not has_output_html:
			error_message = getattr(use_case_result, "error_message", None)
			log.warning("UseCasePresenter received empty output_text; error_message=%s", error_message)
			if isinstance(error_message, str) and error_message.strip():
				nvda_ui.message(error_message)
				return
			nvda_ui.message(_("No result to display."))
			return

		browseable_title = nvda_ui.format_browseable_title(title, get_provider_state())
		self._active_conversation_id = None
		session_state = build_session_state(_)
		use_case_id = None
		prompt_context = getattr(use_case_result, "prompt_context", None)
		if prompt_context is not None:
			use_case_id = getattr(prompt_context, "use_case_id", None)
		copy_text = output_text if has_output_text and not is_html else None
		copy_markdown = output_text if has_output_text else None
		metadata = merge_session_metadata(getattr(use_case_result, "metadata", None), session_state)
		self._result_action_store.clear()
		actions = self._build_result_actions(use_case_id, output_text, use_case_result)
		ui_adapter.render_display(
			DisplayResultViewModel(
				use_case_id=use_case_id,
				title=browseable_title,
				output_text=output_text,
				output_html=output_html,
				is_html=is_html,
				success=True,
				message=getattr(use_case_result, "message", None),
				close_button=True,
				copy_button=True,
				copy_text=copy_text,
				copy_markdown=copy_markdown,
				metadata=metadata,
				actions=tuple(actions),
			)
		)

	def progress_handler(self, event: ProgressEvent) -> None:
		if event.stage == "error":
			ui_adapter.show_error(_("Error"), details=event.message)
			nvda_ui.queue(nvda_ui.message, _("Error: ") + event.message)
			return

		if event.stage in {"start", "collecting_context", "building_prompt", "llm_request", "tool_execution", "complete"}:
			ui_adapter.show_progress(event.message)
			nvda_ui.queue(nvda_ui.message, event.message)

	def _build_chat_metadata(self) -> dict[str, Any]:
		return build_session_state(_, conversation_id=self._active_conversation_id).to_metadata()

	def _build_result_actions(self, use_case_id: str | None, output_text: str | None, use_case_result: Any) -> list[ResultActionViewModel]:
		if not isinstance(output_text, str) or not output_text.strip():
			return []
		if use_case_id not in {"summary", "structure_summary", "describe_image"}:
			return []
		action_token = self._result_action_store.put({
			"initial_text": output_text.strip(),
			"initial_image_base64": getattr(use_case_result, "initial_image_base64", None),
		})
		return [ResultActionViewModel(
			id="open_chat",
			label=_("Open Chat"),
			kind="open_chat",
			payload={
				"token": action_token,
			},
		)]

	def _handle_result_action(self, action_id: str, payload: dict[str, Any] | None) -> None:
		if action_id != "open_chat":
			return
		payload = payload or {}
		token = payload.get("token") if isinstance(payload.get("token"), str) else None
		if token:
			payload = self._result_action_store.pop(token) or payload
		self.open_chat_window(
			initial_text=payload.get("initial_text") if isinstance(payload.get("initial_text"), str) else None,
			initial_image_base64=payload.get("initial_image_base64") if isinstance(payload.get("initial_image_base64"), str) else None,
		)
