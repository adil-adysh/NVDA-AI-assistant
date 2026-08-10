# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from __future__ import annotations

import builtins
from collections.abc import Callable
from typing import Any, cast

from logHandler import log

from ..config.state import ProviderState
from ..core.canonical import Message
from ..core.events import ProgressEvent
from ..core.message_transforms import build_assistant_message, build_user_message
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
	AddItemToChatAction,
	ConversationDeleteAction,
	ConversationNewAction,
	ConversationOpenAction,
	OpenInNewChatAction,
	parse_ui_action,
)


def _translate(message: str) -> str:
	return message


_ = cast(Callable[[str], str], getattr(builtins, "_", _translate))
# `translate` is the extraction keyword recognized by the repo's xgettext
# configuration (site_scons/site_tools/gettexttool); it resolves to the same
# translator as `_` at runtime.  New user-facing labels must go through it so
# they land in the generated POT file.
translate = _


# TRANSLATORS: Result action that adds the page content used by the use case to the current chat.
_CONTEXT_ITEM_ACTION_LABELS: dict[str, str] = {
	"page_content": translate("Add Page Content to Chat"),
	# TRANSLATORS: Result action that adds the extracted page structure to the current chat.
	"page_structure": translate("Add Page Structure to Chat"),
	# TRANSLATORS: Result action that attaches the foreground screenshot to the current chat.
	"screenshot": translate("Add Screenshot to Chat"),
	# TRANSLATORS: Result action that attaches the focused object image to the current chat.
	"focused_image": translate("Add Focused Image to Chat"),
}
# TRANSLATORS: Result action that adds the generated summary to the current chat.
_OUTPUT_ITEM_ACTION_LABELS: dict[str, str] = {
	"summary": translate("Add Summary to Chat"),
	# TRANSLATORS: Result action that adds the generated structure summary to the current chat.
	"structure_summary": translate("Add Structure Summary to Chat"),
	# TRANSLATORS: Result action that adds the generated image description to the current chat.
	"image_description": translate("Add Image Description to Chat"),
	# TRANSLATORS: Result action that adds the generated focused-image description to the current chat.
	"focused_image_description": translate("Add Focused Image Description to Chat"),
}


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
		# Shutdown must never raise: the host may already be gone.
		except Exception:  # pylint: disable=broad-exception-caught
			log.exception("Error closing UI adapter during presenter shutdown")

	def open_chat_window(
		self,
		initial_text: str | None = None,
		initial_image_base64: str | None = None,
		initial_assistant_text: str | None = None,
		conversation_id: str | None = None,
		force_new_conversation: bool = False,
		seed_messages: tuple[Message, ...] | None = None,
	) -> None:
		# When carrying both an image and its description into the conversation,
		# inject the image as a user message seed so it appears in the transcript.
		# When only an image is provided (e.g. open_chat_with_screenshot shortcut),
		# keep it as a composer attachment — the user decides when to send it.
		carry_image_into_history = bool(initial_image_base64 and initial_assistant_text)
		seed_image = initial_image_base64 if carry_image_into_history else None
		composer_image = None if carry_image_into_history else initial_image_base64
		active_conversation_id = self._conversation_service.open_conversation(
			conversation_id=conversation_id,
			initial_assistant_text=initial_assistant_text,
			initial_image_base64=seed_image,
			force_new=force_new_conversation,
			seed_messages=seed_messages,
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
				initial_image_base64=composer_image,
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
		# Session sync must never fail: NVDA stays responsive and the next
		# sync attempt recovers.
		except Exception:  # pylint: disable=broad-exception-caught
			log.exception("Error synchronizing WebView session state after provider change")

	def present_use_case_result(self, use_case_result: Any, title: str) -> None:
		log.debug(
			"UseCasePresenter.present_use_case_result called title=%s result_type=%s",
			title,
			type(use_case_result).__name__,
		)
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
			# TRANSLATORS: Message spoken when a use case returns no content to display.
			nvda_ui.message(_("No result to display."))
			return

		browseable_title = nvda_ui.format_browseable_title(title, get_provider_state())
		provider_state = get_provider_state()
		session_state = build_session_state(
			_, provider_state, available_models=self._get_cached_models(provider_state)
		)
		use_case_id = None
		prompt_context = getattr(use_case_result, "prompt_context", None)
		if prompt_context is not None:
			use_case_id = getattr(prompt_context, "use_case_id", None)
		copy_text = output_text if has_output_text and not is_html else None
		copy_markdown = output_text if has_output_text else None
		metadata = merge_session_metadata(getattr(use_case_result, "metadata", None), session_state)
		self._result_action_store.clear()
		actions = self._build_result_actions(use_case_result)
		# result_actions flag is set by UseCaseSpec and auto-injected into
		# metadata by UseCase.execute_prompted_use_case; avoids hardcoded lists.
		has_result_actions = bool(actions and (metadata or {}).get("result_actions"))
		is_result_action_screen = has_result_actions
		display_presentation = build_display_presentation(
			variant=DISPLAY_VARIANT_RESULT_ACTIONS if is_result_action_screen else DISPLAY_VARIANT_STANDARD,
			initial_focus=FOCUS_TARGET_CONTENT
			if is_result_action_screen or not actions
			else FOCUS_TARGET_PRIMARY_ACTION,
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
		normalized_text = (
			output_text.strip() if isinstance(output_text, str) and output_text.strip() else None
		)
		normalized_html = (
			output_html.strip() if isinstance(output_html, str) and output_html.strip() else None
		)
		if normalized_html is None and normalized_text is not None:
			normalized_html = render_markdown_to_html(normalized_text).strip() or None
		return normalized_text, normalized_html, bool(is_html or normalized_html)

	def progress_handler(self, event: ProgressEvent) -> None:
		if event.stage == "error":
			# The error is spoken exactly once by the background worker's
			# exception handler (present_error); here we only surface the host
			# error dialog so users are not announced the same failure twice.
			ui_adapter.show_error(_("Error"), details=event.message)
			return

		if event.stage == "streaming":
			nvda_ui.play_streaming_tone()
			return

		if event.stage in {
			"start",
			"collecting_context",
			"building_prompt",
			"llm_request",
			"tool_execution",
			"complete",
		}:
			ui_adapter.show_progress(event.message)

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

	def _on_models_cached(self, _provider: str, models: tuple[str, ...]) -> None:
		# Guard against TOCTOU: the provider may have changed between
		# the ModelCache stale-check and this callback.  If it did,
		# discard the stale result — a new refresh will have been
		# queued for the current provider.
		current_state = get_provider_state()
		if current_state.provider != _provider:
			log.debug(
				"Discarding stale model cache callback for %s; active provider is %s",
				_provider,
				current_state.provider,
			)
			return

		ui_adapter.sync_session_state(
			build_session_state(
				_,
				current_state,
				conversation_id=self._conversation_service.current_conversation_id(),
				available_models=models,
				conversation_summaries=self._build_conversation_summaries(),
				readiness=self._readiness_service.evaluate_active(),
			).to_metadata()
		)

	def _build_result_actions(self, use_case_result: Any) -> list[ResultActionViewModel]:
		# Check the flag auto-injected by UseCase.execute_prompted_use_case
		# from UseCaseSpec.result_actions.  Avoids hardcoded use-case-ID lists.
		result_metadata = getattr(use_case_result, "metadata", None) or {}
		if not result_metadata.get("result_actions"):
			return []
		context_items = tuple(
			item
			for item in (getattr(use_case_result, "context_items", None) or ())
			if item.id in _CONTEXT_ITEM_ACTION_LABELS and self._context_item_has_data(item)
		)
		output_items = tuple(
			item
			for item in (getattr(use_case_result, "output_items", None) or ())
			if item.id in _OUTPUT_ITEM_ACTION_LABELS and self._output_item_has_data(item)
		)
		if not context_items and not output_items:
			return []
		# Store the full payload once; each action transports only its token and
		# item id, so large page content or Base64 images never cross the event
		# pipe.  The store is cleared on every new display (see present_use_case_result).
		token = self._result_action_store.put(
			{
				"context_items": [self._serialize_context_item(item) for item in context_items],
				"output_items": [self._serialize_output_item(item) for item in output_items],
			}
		)
		actions = [
			self._build_add_item_action(token, item.id)
			for item in (*context_items, *output_items)
		]
		# TRANSLATORS: Result action that moves the complete use-case context and result into a new conversation.
		actions.append(
			ResultActionViewModel(
				id="open_in_new_chat",
				label=translate("Open in New Chat"),
				kind="open_in_new_chat",
				payload={"token": token},
			)
		)
		return actions

	@staticmethod
	def _context_item_has_data(item: Any) -> bool:
		return bool(
			(isinstance(item.content, str) and item.content.strip())
			or item.image_base64
		)

	@staticmethod
	def _output_item_has_data(item: Any) -> bool:
		return bool(isinstance(item.content, str) and item.content.strip())

	@staticmethod
	def _serialize_context_item(item: Any) -> dict[str, object]:
		return {
			"kind": "context",
			"id": item.id,
			"content": item.content,
			"image_base64": item.image_base64,
		}

	@staticmethod
	def _serialize_output_item(item: Any) -> dict[str, object]:
		return {"kind": "output", "id": item.id, "content": item.content}

	def _build_add_item_action(self, token: str, item_id: str) -> ResultActionViewModel:
		action_id = f"add_{item_id}_to_chat"
		label = _CONTEXT_ITEM_ACTION_LABELS.get(item_id) or _OUTPUT_ITEM_ACTION_LABELS.get(item_id)
		if label is None:
			# Unknown capability id — do not surface a vague action.
			raise ValueError(f"Unknown result action item: {item_id}")
		return ResultActionViewModel(
			id=action_id,
			label=label,
			kind=action_id,
			payload={"token": token, "item_id": item_id},
		)

	def _handle_result_action(self, action_id: str, payload: dict[str, Any] | None) -> None:
		action = parse_ui_action(action_id, payload)
		if action is None:
			return
		self._dispatch_ui_action(action)

	def _dispatch_ui_action(
		self,
		action: ConversationNewAction
		| ConversationOpenAction
		| ConversationDeleteAction
		| AddItemToChatAction
		| OpenInNewChatAction,
	) -> None:
		if isinstance(action, ConversationNewAction):
			self.open_chat_window(force_new_conversation=True)
			return
		if isinstance(action, ConversationOpenAction):
			self.open_chat_window(conversation_id=action.conversation_id)
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
		if isinstance(action, AddItemToChatAction):
			self._dispatch_add_item_to_chat(action)
			return
		if isinstance(action, OpenInNewChatAction):
			self._dispatch_open_in_new_chat(action)

	def _dispatch_add_item_to_chat(self, action: AddItemToChatAction) -> None:
		payload = self._result_action_store.pop(action.token)
		if payload is None:
			log.debug("Result action token expired: action=add_item_to_chat item_id=%s", action.item_id)
			return
		item = self._find_stored_item(payload, action.item_id)
		if item is None:
			log.warning(
				"Result action item missing from stored payload: item_id=%s", action.item_id,
			)
			return
		if item.get("kind") == "context":
			self._conversation_service.add_user_context(
				content=item.get("content") or None,
				image_base64=item.get("image_base64") or None,
			)
		else:
			self._conversation_service.add_assistant_result(item.get("content") or "")
		log.debug(
			"Result action applied: destination=current_chat item_kind=%s item_id=%s conversation_id=%s",
			item.get("kind"),
			action.item_id,
			self._conversation_service.current_conversation_id(),
		)
		self.open_chat_window(force_new_conversation=False)

	def _dispatch_open_in_new_chat(self, action: OpenInNewChatAction) -> None:
		payload = self._result_action_store.pop(action.token)
		if payload is None:
			log.debug("Result action token expired: action=open_in_new_chat")
			return
		seed_messages = self._build_seed_messages_from_payload(payload)
		if not seed_messages:
			log.warning("Open in new chat invoked without seedable result content")
			self.open_chat_window(force_new_conversation=True)
			return
		log.debug(
			"Result action applied: destination=new_chat message_count=%d",
			len(seed_messages),
		)
		self.open_chat_window(seed_messages=seed_messages, force_new_conversation=True)

	def _build_seed_messages_from_payload(self, payload: dict[str, Any]) -> tuple[Message, ...]:
		"""Build complete conversation seeds (user context + assistant result)."""
		messages: list[Message] = []
		context_items = payload.get("context_items") or []
		if context_items:
			text_parts = [
				item.get("content")
				for item in context_items
				if isinstance(item.get("content"), str) and item.get("content").strip()
			]
			image_base64 = next(
				(item.get("image_base64") for item in context_items if item.get("image_base64")),
				None,
			)
			combined_text = "\n\n".join(text_parts) if text_parts else None
			messages.append(build_user_message(text=combined_text, image_base64=image_base64))
		output_items = payload.get("output_items") or []
		if output_items:
			output_text = "\n\n".join(
				item.get("content")
				for item in output_items
				if isinstance(item.get("content"), str) and item.get("content").strip()
			)
			if output_text:
				messages.append(build_assistant_message(text=output_text))
		return tuple(messages)

	@staticmethod
	def _find_stored_item(payload: dict[str, Any], item_id: str) -> dict[str, Any] | None:
		for item in payload.get("context_items", []):
			if item.get("id") == item_id:
				return item
		for item in payload.get("output_items", []):
			if item.get("id") == item_id:
				return item
		return None
