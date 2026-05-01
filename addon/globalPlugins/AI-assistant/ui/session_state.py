# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypedDict

from ..config.state import ProviderState
from ..config.settings import (
	get_ollama_think,
	get_provider_state,
)

Translator = Callable[[str], str]


class SessionProviderInfo(TypedDict):
	provider: str
	model: str


class SessionProviderOption(TypedDict):
	id: str
	label: str


class UISessionMetadata(TypedDict, total=False):
	conversation_id: str
	provider_state: SessionProviderInfo
	available_providers: list[SessionProviderOption]
	available_models: list[str]
	localized_strings: dict[str, str]
	think_enabled: bool
	status_message: str


@dataclass(frozen=True, slots=True)
class UISessionState:
	provider: str
	model: str
	available_providers: tuple[SessionProviderOption, ...]
	available_models: tuple[str, ...]
	localized_strings: dict[str, str]
	think_enabled: bool
	conversation_id: str | None = None

	def to_metadata(self) -> UISessionMetadata:
		metadata: UISessionMetadata = {
			"provider_state": {
				"provider": self.provider,
				"model": self.model,
			},
			"available_providers": [dict(option) for option in self.available_providers],
			"available_models": list(self.available_models),
			"localized_strings": dict(self.localized_strings),
			"think_enabled": self.think_enabled,
		}
		if self.conversation_id:
			metadata["conversation_id"] = self.conversation_id
		return metadata


def build_localized_strings(translate: Translator) -> dict[str, str]:
	return {
		"provider_label": translate("Provider"),
		"model_label": translate("Model"),
		"think_mode_label": translate("Think mode"),
		"app_brand": translate("NVDA AI Assistant"),
		"app_title": translate("Response Workspace"),
		"content_heading": translate("Content"),
		"status_heading": translate("Status"),
		"chat_heading": translate("Chat"),
		"message_label": translate("Message"),
		"response_subtitle": translate("Response"),
		"prompt_subtitle": translate("Prompt"),
		"assistant_heading": translate("Assistant response"),
		"user_heading": translate("User prompt"),
		"session_controls_label": translate("Session controls"),
		"content_actions_label": translate("Content actions"),
		"result_actions_label": translate("Result actions"),
		"message_actions_label": translate("Message actions"),
		"pending_attachments_label": translate("Pending attachments"),
		"attach_button": translate("Attach"),
		"send_button": translate("Send"),
		"copy_text_button": translate("Copy text"),
		"copy_markdown_button": translate("Copy markdown"),
		"copy_response_button": translate("Copy response"),
		"copy_response_markdown_button": translate("Copy response markdown"),
		"copy_table_button": translate("Copy table"),
		"clear_button": translate("Clear"),
		"close_button": translate("Close"),
		"chat_placeholder": translate("Type your message..."),
		"waiting_status": translate("Waiting for host command..."),
		"no_content": translate("No content available."),
		"no_chat_messages": translate("No chat messages available."),
		"thinking_label": translate("Thinking"),
		"thinking_trace_label": translate("Thinking trace"),
		"remove_attachment": translate("Remove"),
		"attachment_fallback_name": translate("Attachment"),
		"initial_image_name": translate("Initial image"),
		"image_attachment_notice": translate("[Image attachment included]"),
		"submitted_status": translate("Message submitted."),
		"attach_failed_status": translate("Unable to attach file."),
		"content_cleared_status": translate("Content cleared."),
		"copied_status": translate("Copied to clipboard."),
		"copy_failed_status": translate("Copy failed."),
		"unknown_schema_status": translate("Unknown host schema."),
		"unsupported_protocol_status": translate("Unsupported host protocol version."),
		"unknown_message_type_status": translate("Unknown host message type."),
		"parse_host_message_failed_status": translate("Unable to parse host message."),
		"apply_host_command_failed_status": translate("Unable to apply host command."),
		"bridge_unavailable_status": translate("WebView bridge unavailable."),
		"window_closed_message": translate("Window closed by host command."),
		"error_prefix": translate("Error"),
		"progress_prefix": translate("Progress"),
		"progress_default_message": translate("Working..."),
		"command_prefix": translate("Command"),
		"unhandled_command_prefix": translate("Unhandled command"),
		"result_action_fallback_label": translate("Action"),
		"host_unavailable_message": translate("AI WebView host is unavailable."),
		"chat_submission_failed_title": translate("Chat submission failed"),
		"attached_file_label": translate("Attached file"),
		"provider_switching_status": translate("Switching provider..."),
		"model_switching_status": translate("Updating model..."),
		"think_mode_updating_status": translate("Updating think mode..."),
		"control_update_failed_status": translate("Unable to update session controls."),
	}


def build_session_state(
	translate: Translator,
	provider_state: ProviderState | None = None,
	conversation_id: str | None = None,
	available_models: tuple[str, ...] | list[str] | None = None,
) -> UISessionState:
	active_provider_state = provider_state or get_provider_state()
	current_model = active_provider_state.model_name.strip()
	resolved_available_models = _ordered_unique_models(
		current_model,
		*(available_models or ()),
	)
	return UISessionState(
		provider=active_provider_state.provider,
		model=active_provider_state.model_name,
		available_providers=(
			{"id": "ollama", "label": translate("Ollama")},
			{"id": "gemini", "label": translate("Gemini")},
			{"id": "openai", "label": translate("OpenAI")},
		),
		available_models=resolved_available_models,
		localized_strings=build_localized_strings(translate),
		think_enabled=get_ollama_think(),
		conversation_id=conversation_id,
	)


def merge_session_metadata(metadata: dict[str, Any] | None, session_state: UISessionState) -> dict[str, Any]:
	merged = dict(metadata or {})
	for key, value in session_state.to_metadata().items():
		merged.setdefault(key, value)
	return merged


def _ordered_unique_models(*candidates: str) -> tuple[str, ...]:
	models: list[str] = []
	seen: set[str] = set()
	for candidate in candidates:
		model_name = str(candidate).strip()
		if not model_name or model_name in seen:
			continue
		seen.add(model_name)
		models.append(model_name)
	return tuple(models)
