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
from .intent import AttentionPolicy, FocusTarget, InteractionMode

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
	interaction_mode: InteractionMode
	controls_visible: bool
	attention_policy: AttentionPolicy
	focus_target: FocusTarget


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


# TRANSLATORS: Strings sent from the Python add-on to the WebView UI.
# These labels appear in the chat workspace, session controls, buttons, and status notifications.
def build_localized_strings(translate: Translator) -> dict[str, str]:
	return {
		# TRANSLATORS: Label for the provider selector in the WebView control panel.
		"provider_label": translate("Provider"),
		# TRANSLATORS: Label for the model selector in the WebView control panel.
		"model_label": translate("Model"),
		# TRANSLATORS: Label for the think mode toggle.
		"think_mode_label": translate("Think mode"),
		# TRANSLATORS: Brand name shown at the top of the WebView.
		"app_brand": translate("NVDA AI Assistant"),
		# TRANSLATORS: Window title shown in the WebView header.
		"app_title": translate("Response Workspace"),
		# TRANSLATORS: Heading for the main content area.
		"content_heading": translate("Content"),
		# TRANSLATORS: Heading for the status panel.
		"status_heading": translate("Status"),
		# TRANSLATORS: Heading for the chat panel.
		"chat_heading": translate("Chat"),
		# TRANSLATORS: Label for the chat composer field.
		"message_label": translate("Message"),
		# TRANSLATORS: Subtitle shown for assistant messages.
		"response_subtitle": translate("Response"),
		# TRANSLATORS: Subtitle shown for user prompts.
		"prompt_subtitle": translate("Prompt"),
		# TRANSLATORS: Label for the assistant response section.
		"assistant_heading": translate("Assistant response"),
		# TRANSLATORS: Label for the user prompt section.
		"user_heading": translate("User prompt"),
		# TRANSLATORS: Label for the session controls section.
		"session_controls_label": translate("Session controls"),
		# TRANSLATORS: Label for the content action toolbar.
		"content_actions_label": translate("Content actions"),
		# TRANSLATORS: Label for result action buttons.
		"result_actions_label": translate("Result actions"),
		# TRANSLATORS: Label for per-message actions.
		"message_actions_label": translate("Message actions"),
		# TRANSLATORS: Label for the pending attachments area.
		"pending_attachments_label": translate("Pending attachments"),
		# TRANSLATORS: Button text for the file attach action.
		"attach_button": translate("Upload image"),
		# TRANSLATORS: Button text for sending a chat message.
		"send_button": translate("Send"),
		# TRANSLATORS: Button text for copying plain text.
		"copy_text_button": translate("Copy text"),
		# TRANSLATORS: Button text for copying markdown.
		"copy_markdown_button": translate("Copy markdown"),
		# TRANSLATORS: Button text for copying an assistant response.
		"copy_response_button": translate("Copy response"),
		# TRANSLATORS: Button text for copying an assistant response as markdown.
		"copy_response_markdown_button": translate("Copy response markdown"),
		# TRANSLATORS: Button text for copying a table from a response.
		"copy_table_button": translate("Copy table"),
		# TRANSLATORS: Button text for clearing displayed content.
		"clear_button": translate("Clear"),
		# TRANSLATORS: Button text for closing the WebView host.
		"close_button": translate("Close"),
		# TRANSLATORS: Placeholder text displayed in the chat composer.
		"chat_placeholder": translate("Type your message..."),
		# TRANSLATORS: Status text shown while waiting for a host command.
		"waiting_status": translate("Waiting for host command..."),
		# TRANSLATORS: Message shown when no display content exists.
		"no_content": translate("No content available."),
		# TRANSLATORS: Message shown when the chat transcript is empty.
		"no_chat_messages": translate("No chat messages available."),
		# TRANSLATORS: Label shown for a collapsed thinking block.
		"thinking_label": translate("Thinking"),
		# TRANSLATORS: Label for thinking trace content when present in a response.
		"thinking_trace_label": translate("Thinking trace"),
		# TRANSLATORS: Button text for removing an attachment.
		"remove_attachment": translate("Remove"),
		# TRANSLATORS: Fallback name for an attachment when no file name is available.
		"attachment_fallback_name": translate("Attachment"),
		# TRANSLATORS: Label for the initial image attachment item.
		"initial_image_name": translate("Initial image"),
		# TRANSLATORS: Notice text inserted when an image attachment is included.
		"image_attachment_notice": translate("[Image attachment included]"),
		# TRANSLATORS: Alt text for attached images when no specific alt text is provided.
		"image_attachment_alt": translate("Attached image"),
		# TRANSLATORS: Status text shown after a chat message is submitted.
		"submitted_status": translate("Message submitted."),
		# TRANSLATORS: Status text shown when attachment upload fails.
		"attach_failed_status": translate("Unable to attach file."),
		# TRANSLATORS: Status text shown when content has been cleared.
		"content_cleared_status": translate("Content cleared."),
		# TRANSLATORS: Status text shown when clipboard copy succeeds.
		"copied_status": translate("Copied to clipboard."),
		# TRANSLATORS: Status text shown when clipboard copy fails.
		"copy_failed_status": translate("Copy failed."),
		# TRANSLATORS: Status text shown for unsupported host metadata.
		"unknown_schema_status": translate("Unknown host schema."),
		# TRANSLATORS: Status text shown when the UI protocol version is unsupported.
		"unsupported_protocol_status": translate("Unsupported host protocol version."),
		# TRANSLATORS: Status text shown when an unknown host message type is received.
		"unknown_message_type_status": translate("Unknown host message type."),
		# TRANSLATORS: Status text shown when a host message cannot be parsed.
		"parse_host_message_failed_status": translate("Unable to parse host message."),
		# TRANSLATORS: Status text shown when a host command cannot be applied.
		"apply_host_command_failed_status": translate("Unable to apply host command."),
		# TRANSLATORS: Status text shown when the WebView bridge is unavailable.
		"bridge_unavailable_status": translate("WebView bridge unavailable."),
		# TRANSLATORS: Status text shown when the host window was closed by the host.
		"window_closed_message": translate("Window closed by host command."),
		# TRANSLATORS: Prefix label for error messages.
		"error_prefix": translate("Error"),
		# TRANSLATORS: Prefix label for progress messages.
		"progress_prefix": translate("Progress"),
		# TRANSLATORS: Default progress message when no other text is available.
		"progress_default_message": translate("Working..."),
		# TRANSLATORS: Prefix label used in host command logs.
		"command_prefix": translate("Command"),
		# TRANSLATORS: Prefix shown when an unhandled command is received.
		"unhandled_command_prefix": translate("Unhandled command"),
		# TRANSLATORS: Fallback label for generic action buttons.
		"result_action_fallback_label": translate("Action"),
		# TRANSLATORS: Message shown when the WebView host is unavailable.
		"host_unavailable_message": translate("AI WebView host is unavailable."),
		# TRANSLATORS: Title shown when chat submission fails.
		"chat_submission_failed_title": translate("Chat submission failed"),
		# TRANSLATORS: Label used when building attachment context for file uploads.
		"attached_file_label": translate("Attached file"),
		# TRANSLATORS: Status text shown while switching providers.
		"provider_switching_status": translate("Switching provider..."),
		# TRANSLATORS: Status text shown while the model selection is updating.
		"model_switching_status": translate("Updating model..."),
		# TRANSLATORS: Status text shown while think mode is updating.
		"think_mode_updating_status": translate("Updating think mode..."),
		# TRANSLATORS: Status text shown when control updates fail.
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
