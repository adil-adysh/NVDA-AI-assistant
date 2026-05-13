# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from __future__ import annotations

import builtins
from collections.abc import Callable
from typing import Any, cast

from logHandler import log

from ..config.state import ProviderState
from ..core.events import ProgressEvent
from ..service.chat import ChatCoordinator, ConversationService
from ..service.provider_catalog import ProviderCatalogService
from ..service.provider_readiness import ProviderReadinessService
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
from .model_cache import ModelCache
from .ui_actions import (
	AttachToCurrentAction,
	ConversationDeleteAction,
	ConversationNewAction,
	ConversationOpenAction,
	OpenChatAction,
	parse_ui_action,
	serialize_ui_action,
)


def _translate(message: str) -> str:
	return message


_ = cast(Callable[[str], str], getattr(builtins, "_", _translate))


class UseCasePresenter:
	def __init__(
		self,
		chat_coordinator: ChatCoordinator,
		conversation_service: ConversationService,
		tool_registry: ToolRegistry,
		provider_catalog: ProviderCatalogService | None = None,
		readiness_service: ProviderReadinessService | None = None,
	) -> None:
		self._chat_coordinator = chat_coordinator
		self._conversation_service = conversation_service
		self._tool_registry = tool_registry
		self._provider_catalog = provider_catalog or ProviderCatalogService()
		self._readiness_service = readiness_service or ProviderReadinessService()
		self._model_cache = ModelCache(
			provider_catalog=self._provider_catalog,
			on_models_updated=self._on_models_cached,
		)
		self._result_action_store = ResultActionStore()
		ui_adapter.register_result_action_handler(self._handle_result_action)
		ui_adapter.register_session_metadata_provider(self._build_chat_metadata)

	def close(self) -> None:
		self._model_cache.close()
		try:
			ui_adapter.close()
		except Exception:
			log.exception("Error closing UI adapter during presenter shutdown")

	def open_chat_window(
		self,
		initial_text: str | None = None,
		initial_image_base64: str | None = None,
		initial_assistant_text: str | None = None,
		conversation_id: str | None = None,
		force_new_conversation: bool = False,
	) -> None:
		active_conversation_id = self._conversation_service.open_conversation(
			conversation_id=conversation_id,
			initial_assistant_text=initial_assistant_text,
			force_new=force_new_conversation,
		)
		provider_state = get_provider_state()
		session_state = build_session_state(
			_,
			provider_state,
			conversation_id=active_conversation_id,
			available_models=self._get_cached_models(provider_state),
			conversation_summaries=self._build_conversation_summaries(),
			readiness=self._readiness_service.evaluate_active(),
		)
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
			history_messages=self._conversation_service.history_transport(),
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
					conversation_id=self._conversation_service.current_conversation_id(),
					available_models=self._get_cached_models(provider_state),
					conversation_summaries=self._build_conversation_summaries(),
					readiness=self._readiness_service.evaluate_active(),
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
			initial_focus=FOCUS_TARGET_CONTENT if is_result_action_screen or not actions else FOCUS_TARGET_PRIMARY_ACTION,
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

		if event.stage == "streaming":
			nvda_ui.play_streaming_tone()
			return

		if event.stage in {"start", "collecting_context", "building_prompt", "llm_request", "tool_execution", "complete"}:
			ui_adapter.show_progress(event.message)
			nvda_ui.queue(nvda_ui.message, event.message)

	def _build_chat_metadata(self) -> dict[str, Any]:
		provider_state = get_provider_state()
		return build_session_state(
			_,
			provider_state,
			conversation_id=self._conversation_service.current_conversation_id(),
			available_models=self._get_cached_models(provider_state),
			conversation_summaries=self._build_conversation_summaries(),
			readiness=self._readiness_service.evaluate_active(),
		).to_metadata()

	def _build_conversation_summaries(self) -> list[dict[str, object]]:
		return self._conversation_service.list_conversation_summaries()

	def _get_cached_models(self, provider_state: ProviderState) -> tuple[str, ...]:
		return self._model_cache.get(provider_state)

	def _refresh_available_models_async(self, provider_state: ProviderState) -> None:
		self._model_cache.refresh_async(provider_state)

	def _on_models_cached(self, provider: str, models: tuple[str, ...]) -> None:
		ui_adapter.sync_session_state(
			build_session_state(
				_,
				get_provider_state(),
				conversation_id=self._conversation_service.current_conversation_id(),
				available_models=models,
				conversation_summaries=self._build_conversation_summaries(),
				readiness=self._readiness_service.evaluate_active(),
			).to_metadata()
		)

	def _build_result_actions(self, use_case_id: str | None, output_text: str | None, use_case_result: Any) -> list[ResultActionViewModel]:
		if not isinstance(output_text, str) or not output_text.strip():
			return []
		if use_case_id not in {"summary", "structure_summary", "describe_image"}:
			return []
		# ── Open Chat (new conversation, seed text via token store) ──
		stored_action = OpenChatAction(
			assistant_seed_text=output_text.strip(),
			initial_image_base64=getattr(use_case_result, "initial_image_base64", None),
			force_new_conversation=True,
		)
		_stored_id, stored_payload = serialize_ui_action(stored_action)
		token = self._result_action_store.put(stored_payload)
		transport = OpenChatAction(token=token)
		open_chat_id, open_chat_payload = serialize_ui_action(transport)
		# ── Attach to Current (seed text stored, resolved on dispatch) ──
		attach_stored_action = AttachToCurrentAction()
		_attach_stored_id, attach_stored_payload = serialize_ui_action(attach_stored_action)
		# Store the seed text payload under a new token so the resolved action
		# carries the summary/description to inject into the current conversation.
		attach_seed_payload: dict[str, object] = {
			"initial_assistant_text": output_text.strip(),
		}
		image_b64 = getattr(use_case_result, "initial_image_base64", None)
		if image_b64:
			attach_seed_payload["initial_image_base64"] = image_b64
		attach_token = self._result_action_store.put(attach_seed_payload)
		attach_transport = AttachToCurrentAction(token=attach_token)
		attach_id, attach_payload = serialize_ui_action(attach_transport)
		return [
			ResultActionViewModel(
				id=attach_id,
				label=_("Add to current chat"),
				kind=attach_id,
				payload=attach_payload,
			),
			ResultActionViewModel(
				id=open_chat_id,
				label=_("Open Chat"),
				kind=open_chat_id,
				payload=open_chat_payload,
			),
		]

	def _handle_result_action(self, action_id: str, payload: dict[str, Any] | None) -> None:
		action = parse_ui_action(action_id, payload)
		if action is None:
			return
		self._dispatch_ui_action(action)

	def _dispatch_ui_action(
		self,
		action: ConversationNewAction | ConversationOpenAction | ConversationDeleteAction | OpenChatAction | AttachToCurrentAction,
	) -> None:
		if isinstance(action, ConversationNewAction):
			self.open_chat_window(force_new_conversation=True)
			return
		if isinstance(action, ConversationOpenAction):
			self.open_chat_window(conversation_id=action.conversation_id)
			return
		if isinstance(action, AttachToCurrentAction):
			initial_text = None
			initial_image = None
			if action.token:
				stored_payload = self._result_action_store.pop(action.token)
				if isinstance(stored_payload, dict):
					initial_text = stored_payload.get("initial_assistant_text")
					initial_image = stored_payload.get("initial_image_base64")
			self.open_chat_window(
				initial_assistant_text=initial_text,
				initial_image_base64=initial_image,
				force_new_conversation=False,
			)
			return
		if isinstance(action, ConversationDeleteAction):
			delete_result = self._conversation_service.delete_conversation(action.conversation_id)
			if not delete_result.deleted:
				return
			if delete_result.active_conversation_deleted:
				self.open_chat_window(force_new_conversation=True)
			else:
				self.update_provider_state()
			return
		resolved_action = action
		if isinstance(action, OpenChatAction) and action.token:
			stored_payload = self._result_action_store.pop(action.token)
			if stored_payload is not None:
				stored_action = parse_ui_action("open_chat", stored_payload)
				if isinstance(stored_action, OpenChatAction):
					resolved_action = stored_action
		if not isinstance(resolved_action, OpenChatAction):
			return
		self.open_chat_window(
			initial_assistant_text=resolved_action.assistant_seed_text,
			initial_image_base64=resolved_action.initial_image_base64,
			force_new_conversation=resolved_action.force_new_conversation,
		)
