# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from __future__ import annotations

import builtins
import threading
from collections.abc import Callable
from typing import Any, cast
from uuid import uuid4

from logHandler import log

from ..config.state import ProviderState
from ..core.events import ProgressEvent
from ..core.message_transforms import build_assistant_message
from ..service.chat import ChatCoordinator
from ..tools import ToolRegistry
from ..config.settings import get_provider_state
from ..ui.adapter import ui_adapter
from ..ui.action_store import ResultActionStore
from ..ui.intent import (
	ATTENTION_POLICY_ACTIVATE_AND_FOCUS,
	ATTENTION_POLICY_FOREGROUND_IF_BACKGROUND,
	DISPLAY_VARIANT_RESULT_ACTIONS,
	DISPLAY_VARIANT_STANDARD,
	FOCUS_TARGET_COMPOSER,
	FOCUS_TARGET_CONTENT,
	FOCUS_TARGET_PRIMARY_ACTION,
	INTERACTION_MODE_CHAT,
	INTERACTION_MODE_DISPLAY,
	TOOLBAR_ACTION_CLEAR,
	TOOLBAR_ACTION_CLOSE,
	TOOLBAR_ACTION_COPY_MARKDOWN,
	TOOLBAR_ACTION_COPY_TEXT,
	build_display_presentation,
	merge_presentation_intent,
)
from ..ui import nvda_ui
from ..ui.session_state import build_session_state, merge_session_metadata
from ..ui.view_models import ChatWindowViewModel, DisplayResultViewModel, ResultActionViewModel
from ..utils.markdown import render_markdown_to_html


def _translate(message: str) -> str:
	return message


_ = cast(Callable[[str], str], getattr(builtins, "_", _translate))


class UseCasePresenter:
	def __init__(self, chat_coordinator: ChatCoordinator, tool_registry: ToolRegistry) -> None:
		self._chat_coordinator = chat_coordinator
		self._tool_registry = tool_registry
		self._active_conversation_id: str | None = None
		self._available_models_by_provider: dict[str, tuple[str, ...]] = {}
		self._model_cache_lock = threading.RLock()
		self._result_action_store = ResultActionStore()
		ui_adapter.register_result_action_handler(self._handle_result_action)
		ui_adapter.register_session_metadata_provider(self._build_chat_metadata)

	def open_chat_window(
		self,
		initial_text: str | None = None,
		initial_image_base64: str | None = None,
		initial_assistant_text: str | None = None,
	) -> None:
		self._active_conversation_id = str(uuid4())
		self._chat_coordinator.reset()
		provider_state = get_provider_state()
		session_state = build_session_state(
			_,
			provider_state,
			conversation_id=self._active_conversation_id,
			available_models=self._get_cached_models(provider_state),
		)
		seed_messages = self._build_seed_messages(initial_assistant_text)
		if seed_messages:
			self._chat_coordinator.seed_history(seed_messages)
		ui_adapter.open_chat_view(
			ChatWindowViewModel(
				use_case_id=None,
				title=_("AI Chat"),
				initial_text=initial_text,
				initial_image_base64=initial_image_base64,
				metadata=merge_presentation_intent(
					session_state.to_metadata(),
					interaction_mode=INTERACTION_MODE_CHAT,
					controls_visible=True,
					attention_policy=ATTENTION_POLICY_ACTIVATE_AND_FOCUS,
					focus_target=FOCUS_TARGET_COMPOSER,
				),
			),
			coordinator=self._chat_coordinator,
			tool_registry=self._tool_registry,
			history_messages=self._build_seed_history_messages(initial_assistant_text),
		)
		self._refresh_available_models_async(provider_state)

	def update_provider_state(self, provider_state: ProviderState | None = None) -> None:
		try:
			if provider_state is None:
				provider_state = get_provider_state()
			ui_adapter.sync_session_state(
				build_session_state(
					_,
					provider_state,
					conversation_id=self._active_conversation_id,
					available_models=self._get_cached_models(provider_state),
				).to_metadata()
			)
			self._refresh_available_models_async(provider_state)
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

		output_text, output_html, is_html = self._normalize_display_outputs(output_text, output_html, is_html)

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
		provider_state = get_provider_state()
		session_state = build_session_state(_, provider_state, available_models=self._get_cached_models(provider_state))
		use_case_id = None
		prompt_context = getattr(use_case_result, "prompt_context", None)
		if prompt_context is not None:
			use_case_id = getattr(prompt_context, "use_case_id", None)
		copy_text = output_text if has_output_text and not is_html else None
		copy_markdown = output_text if has_output_text else None
		metadata = merge_session_metadata(getattr(use_case_result, "metadata", None), session_state)
		self._result_action_store.clear()
		actions = self._build_result_actions(use_case_id, output_text, use_case_result)
		is_result_action_screen = bool(actions) and use_case_id in {"summary", "structure_summary", "describe_image"}
		display_presentation = build_display_presentation(
			variant=DISPLAY_VARIANT_RESULT_ACTIONS if is_result_action_screen else DISPLAY_VARIANT_STANDARD,
			initial_focus=FOCUS_TARGET_PRIMARY_ACTION if actions else FOCUS_TARGET_CONTENT,
			toolbar_actions=self._build_display_toolbar_actions(include_clear=not is_result_action_screen),
		)
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
				display_presentation=display_presentation,
				interaction_mode=INTERACTION_MODE_DISPLAY,
				controls_visible=not is_result_action_screen,
				attention_policy=ATTENTION_POLICY_FOREGROUND_IF_BACKGROUND,
			)
		)

	def _build_display_toolbar_actions(self, *, include_clear: bool) -> tuple[str, ...]:
		actions = [
			TOOLBAR_ACTION_COPY_TEXT,
			TOOLBAR_ACTION_COPY_MARKDOWN,
			TOOLBAR_ACTION_CLOSE,
		]
		if include_clear:
			actions.insert(2, TOOLBAR_ACTION_CLEAR)
		return tuple(actions)

	def _normalize_display_outputs(
		self,
		output_text: Any,
		output_html: Any,
		is_html: bool,
	) -> tuple[str | None, str | None, bool]:
		normalized_text = output_text.strip() if isinstance(output_text, str) and output_text.strip() else None
		normalized_html = output_html.strip() if isinstance(output_html, str) and output_html.strip() else None
		if normalized_html is None and normalized_text is not None:
			normalized_html = render_markdown_to_html(normalized_text).strip() or None
		return normalized_text, normalized_html, bool(is_html or normalized_html)

	def progress_handler(self, event: ProgressEvent) -> None:
		if event.stage == "error":
			ui_adapter.show_error(_("Error"), details=event.message)
			nvda_ui.queue(nvda_ui.message, _("Error: ") + event.message)
			return

		if event.stage in {"start", "collecting_context", "building_prompt", "llm_request", "tool_execution", "complete"}:
			ui_adapter.show_progress(event.message)
			nvda_ui.queue(nvda_ui.message, event.message)

	def _build_chat_metadata(self) -> dict[str, Any]:
		provider_state = get_provider_state()
		return build_session_state(
			_,
			provider_state,
			conversation_id=self._active_conversation_id,
			available_models=self._get_cached_models(provider_state),
		).to_metadata()

	def _get_cached_models(self, provider_state: ProviderState) -> tuple[str, ...]:
		with self._model_cache_lock:
			return self._available_models_by_provider.get(provider_state.provider, ())

	def _refresh_available_models_async(self, provider_state: ProviderState) -> None:
		threading.Thread(
			target=self._refresh_available_models,
			args=(provider_state,),
			name=f"ModelCatalogRefresh-{provider_state.provider}",
			daemon=True,
		).start()

	def _refresh_available_models(self, provider_state: ProviderState) -> None:
		current_provider_state = get_provider_state()
		if current_provider_state.provider != provider_state.provider:
			log.debug(
				"Skipping stale model refresh for %s; active provider is %s",
				provider_state.provider,
				current_provider_state.provider,
			)
			return

		try:
			models = tuple(
				model.id
				for model in self._chat_coordinator.list_models()
				if isinstance(model.id, str) and model.id.strip()
			)
		except Exception:
			log.exception("Error refreshing provider models for %s", provider_state.provider)
			return

		if not models:
			return

		current_provider_state = get_provider_state()
		if current_provider_state.provider != provider_state.provider:
			log.debug(
				"Discarding stale model refresh result for %s; active provider is %s",
				provider_state.provider,
				current_provider_state.provider,
			)
			return

		with self._model_cache_lock:
			self._available_models_by_provider[provider_state.provider] = models

		ui_adapter.sync_session_state(
			build_session_state(
				_,
				current_provider_state,
				conversation_id=self._active_conversation_id,
				available_models=models,
			).to_metadata()
		)

	def _build_result_actions(self, use_case_id: str | None, output_text: str | None, use_case_result: Any) -> list[ResultActionViewModel]:
		if not isinstance(output_text, str) or not output_text.strip():
			return []
		if use_case_id not in {"summary", "structure_summary", "describe_image"}:
			return []
		action_token = self._result_action_store.put({
			"assistant_seed_text": output_text.strip(),
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
			initial_assistant_text=payload.get("assistant_seed_text") if isinstance(payload.get("assistant_seed_text"), str) else None,
			initial_image_base64=payload.get("initial_image_base64") if isinstance(payload.get("initial_image_base64"), str) else None,
		)

	def _build_seed_messages(self, initial_assistant_text: str | None) -> tuple[Any, ...]:
		if not isinstance(initial_assistant_text, str) or not initial_assistant_text.strip():
			return ()
		return (build_assistant_message(text=initial_assistant_text.strip()),)

	def _build_seed_history_messages(self, initial_assistant_text: str | None) -> list[dict[str, Any]]:
		if not isinstance(initial_assistant_text, str) or not initial_assistant_text.strip():
			return []
		rendered_html = render_markdown_to_html(initial_assistant_text.strip()).strip()
		content: list[dict[str, Any]]
		if rendered_html:
			content = [{"type": "html", "html": rendered_html}]
		else:
			content = [{"type": "text", "text": initial_assistant_text.strip()}]
		return [{
			"id": f"seed-assistant-{uuid4()}",
			"role": "assistant",
			"content": content,
		}]
