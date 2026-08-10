# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any
from dataclasses import dataclass

from ..config.state import ProviderState
from ..config.settings import (
	get_provider_state,
	get_think,
)
from ..service.provider_readiness import (
	ProviderReadiness,
	ProviderReadinessReason,
	ProviderReadinessService,
	ProviderReadinessState,
	get_provider_display_name,
)
from .session_types import (
	SessionConversationSummary,
	SessionProviderOption,
	SessionProviderStatus,
	Translator,
	UISessionMetadata,
)


@dataclass(frozen=True, slots=True)
class UISessionState:
	provider: str
	model: str
	provider_status: SessionProviderStatus
	available_providers: tuple[SessionProviderOption, ...]
	available_models: tuple[str, ...]
	available_model_labels: dict[str, str]
	conversation_summaries: tuple[SessionConversationSummary, ...]
	localized_strings: dict[str, str]
	think_enabled: bool
	chat_enabled: bool
	status_message: str | None = None
	conversation_id: str | None = None

	def to_metadata(self) -> UISessionMetadata:
		metadata: UISessionMetadata = {
			"provider_state": {
				"provider": self.provider,
				"model": self.model,
			},
			"provider_status": dict(self.provider_status),
			"available_providers": [dict(option) for option in self.available_providers],
			"available_models": list(self.available_models),
			"available_model_labels": dict(self.available_model_labels),
			"conversation_summaries": [dict(item) for item in self.conversation_summaries],
			"localized_strings": dict(self.localized_strings),
			"think_enabled": self.think_enabled,
			"chat_enabled": self.chat_enabled,
		}
		if self.conversation_id:
			metadata["conversation_id"] = self.conversation_id
		if self.status_message:
			metadata["status_message"] = self.status_message
		return metadata


_READINESS_SERVICE = ProviderReadinessService()


def _resolve_think_enabled(provider: str) -> bool:
	"""Return the think-mode setting for the active provider."""
	return get_think(provider)


def _build_available_providers(translate: Translator) -> tuple[SessionProviderOption, ...]:
	"""Build the list of available providers from the registry.

	Uses :data:`providers.registry.PROVIDER_IDS` and
	:func:`providers.registry.provider_display_name` so the provider
	list stays in a single place and the UI layer never hardcodes
	provider IDs or display names.
	"""
	from ..providers.registry import PROVIDER_IDS, provider_display_name

	return tuple(
		{"id": pid, "label": translate(provider_display_name(pid))}
		for pid in PROVIDER_IDS
	)


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
		# TRANSLATORS: Heading for the recent conversations rail in the chat workspace.
		"conversation_history_heading": translate("Recent conversations"),
		# TRANSLATORS: Button text for starting a new stored conversation.
		"new_conversation_button": translate("New conversation"),
		# TRANSLATORS: Button text for collapsing the conversation history sidebar.
		"collapse_conversation_sidebar_button": translate("Hide conversations"),
		# TRANSLATORS: Button text for expanding the conversation history sidebar.
		"expand_conversation_sidebar_button": translate("Show conversations"),
		# TRANSLATORS: Label announcing the currently selected conversation in the chat workspace.
		"current_conversation_label": translate("Current conversation"),
		# TRANSLATORS: Button text for deleting a stored conversation.
		"delete_conversation_button": translate("Delete"),
		# TRANSLATORS: Empty-state text shown when no stored conversations exist yet.
		"empty_conversations_state": translate("No stored conversations yet."),
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
		# TRANSLATORS: Notice spoken when a chat response was discarded because the conversation changed while it was being generated.
		"conversation_changed_notice": translate("Response discarded because the conversation changed."),
		# TRANSLATORS: Message shown when no display content exists.
		"no_content": translate("No content available."),
		# TRANSLATORS: Message shown when the chat transcript is empty.
		"no_chat_messages": translate("No messages yet. Start the conversation by typing a message below."),
		# TRANSLATORS: Message shown when the selected conversation contains no messages.
		"selected_conversation_empty": translate("This conversation has no messages yet."),
		# TRANSLATORS: Accessible label for the chat transcript live region.
		"chat_transcript_label": translate("Chat messages"),
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
		# TRANSLATORS: Subtitle shown for assistant messages that are still being streamed.
		"response_streaming_subtitle": translate("Response in progress"),
		# TRANSLATORS: Status text shown when file attachment loading fails.
		"attachment_load_failed": translate("Failed to load {file_name}"),
		# TRANSLATORS: Status text shown when one or more file attachments have been added.
		"attachments_added_status": translate("{count} attachment(s) added."),
	}


def build_session_state(
	translate: Translator,
	provider_state: ProviderState | None = None,
	conversation_id: str | None = None,
	available_models: tuple[str, ...] | list[str] | None = None,
	available_model_labels: dict[str, str] | None = None,
	conversation_summaries: tuple[SessionConversationSummary, ...] | list[SessionConversationSummary] | None = None,
	readiness: ProviderReadiness | None = None,
) -> UISessionState:
	active_provider_state = provider_state or get_provider_state()
	resolved_readiness = readiness or _READINESS_SERVICE.evaluate_active()
	current_model = active_provider_state.model_name.strip()
	resolved_available_models = _ordered_unique_models(
		current_model,
		*(available_models or ()),
	)
	# Filter models to only show enabled ones in the host UI
	resolved_available_models = _filter_available_models(
		resolved_available_models,
		active_provider_state.provider,
	)
	# Build human-readable labels for the model dropdown.
	# Local providers (e.g. LiteRT-LM) use canonical repo IDs as
	# identifiers — the label map translates those to user-facing
	# display names so the WebView shows the same names as the
	# model manager dialog.
	resolved_labels = _resolve_model_labels(
		active_provider_state.provider,
		resolved_available_models,
		available_model_labels,
	)
	return UISessionState(
		provider=active_provider_state.provider,
		model=active_provider_state.model_name,
		provider_status={
			"state": resolved_readiness.state.value,
			"can_infer": resolved_readiness.can_infer,
			"can_list_models": resolved_readiness.can_list_models,
			**({"reason": resolved_readiness.reason.value} if resolved_readiness.reason is not None else {}),
		},
		available_providers=_build_available_providers(translate),
		available_models=resolved_available_models,
		available_model_labels=resolved_labels,
		conversation_summaries=tuple(conversation_summaries or ()),
		localized_strings=build_localized_strings(translate),
		think_enabled=_resolve_think_enabled(provider_state.provider),
		chat_enabled=resolved_readiness.can_infer,
		status_message=build_provider_status_message(translate, resolved_readiness),
		conversation_id=conversation_id,
	)


def merge_session_metadata(metadata: dict[str, Any] | None, session_state: UISessionState) -> dict[str, Any]:
	merged = dict(metadata or {})
	session_metadata = session_state.to_metadata()
	for key, value in session_metadata.items():
		merged[key] = value
	if "status_message" not in session_metadata:
		merged.pop("status_message", None)
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


def build_provider_status_message(translate: Translator, readiness: ProviderReadiness | None) -> str | None:
	if readiness is None or readiness.state is ProviderReadinessState.READY or readiness.can_infer:
		return None

	# TRANSLATORS: Provider display name used in status messages.
	provider_label = translate(get_provider_display_name(readiness.provider))
	if readiness.reason is ProviderReadinessReason.MISSING_CREDENTIALS:
		if readiness.provider == "gemini":
			# TRANSLATORS: Guidance shown when Gemini is selected without an API key or bearer token.
			return translate("Gemini is selected but not configured. Set an API key or bearer token in settings.")
		if readiness.provider == "openai":
			# TRANSLATORS: Guidance shown when OpenAI is selected without an API key.
			return translate("OpenAI is selected but not configured. Set an API key in settings.")
		# TRANSLATORS: Guidance shown when the selected provider is missing credentials.
		return translate("{provider} is selected but missing required credentials.").format(provider=provider_label)
	if readiness.reason is ProviderReadinessReason.MISSING_MODEL:
		# TRANSLATORS: Guidance shown when the selected provider has no configured model.
		return translate("{provider} is selected but no model is configured.").format(provider=provider_label)
	if readiness.reason in {ProviderReadinessReason.MISSING_SERVER_URL, ProviderReadinessReason.MISSING_BASE_URL}:
		# TRANSLATORS: Guidance shown when the selected provider is missing a server or base URL.
		return translate("{provider} is selected but its server address is not configured.").format(provider=provider_label)
	if readiness.reason is ProviderReadinessReason.MISSING_CHAT_PATH:
		# TRANSLATORS: Guidance shown when OpenAI is selected without a chat endpoint path.
		return translate("OpenAI is selected but the chat endpoint path is not configured.")
	if readiness.reason is ProviderReadinessReason.UNSUPPORTED_MODEL:
		if readiness.provider == "gemini":
			# TRANSLATORS: Guidance shown when a Gemini model is selected that only works through Live API or Interactions API workflows.
			return translate("The selected Gemini model is not supported here. Choose a standard Gemini model instead of a Live API or Interactions-only preview model.")
		# TRANSLATORS: Guidance shown when the selected model is not supported for the current workflow.
		return translate("The selected {provider} model is not supported for this workflow.").format(provider=provider_label)
	# TRANSLATORS: Guidance shown when the selected provider is not ready but no specific reason is available.
	return translate("{provider} is selected but not fully configured.").format(provider=provider_label)


def _filter_available_models(
	available_models: tuple[str, ...],
	provider: str,
) -> tuple[str, ...]:
	"""Filter models to only those not explicitly disabled by the user.

	Model readiness (downloaded / imported) is already handled by
	:meth:`ModelManagerProvider.get_available_model_ids`.

	Models that appear in *available_models* but are not yet tracked
	in the persistent store are treated as implicitly enabled — the
	store tracks only models the user has explicitly toggled in the
	model manager dialog.  This ensures newly downloaded models
	appear in the WebView dropdown immediately without requiring
	the user to visit the model manager first.
	"""
	from .enabled_models import EnabledModelsStore

	store = EnabledModelsStore()
	enabled_ids = store.get_enabled(provider)
	if not enabled_ids:
		return available_models  # First run — nothing tracked yet

	# Auto-register newly discovered models so they appear in the
	# dropdown without the user needing to enable them explicitly.
	# Only models the user has explicitly **disabled** (removed from
	# the enabled set via the model manager toggle) are filtered out.
	newly_discovered = [m for m in available_models if m not in enabled_ids]
	if newly_discovered:
		for model_id in newly_discovered:
			store.set_enabled(provider, model_id, True)
		enabled_ids = store.get_enabled(provider)

	return tuple(m for m in available_models if m in enabled_ids)


def _resolve_model_labels(
	provider: str,
	available_models: tuple[str, ...],
	explicit_labels: dict[str, str] | None = None,
) -> dict[str, str]:
	"""Build a ``canonical_id → display_name`` map for the WebView dropdown.

	Prefers *explicit_labels* when provided by the caller (e.g. from a
	model cache).  Otherwise queries :meth:`ModelManagerProvider.list_managed_models`
	to map canonical IDs back to the human-readable names shown in the
	model manager dialog.

	Falls back gracefully — when the model manager is unavailable or a
	model has no display name entry, the raw ID is used by the WebView.
	"""
	if explicit_labels:
		return dict(explicit_labels)

	available_set = set(available_models)
	if not available_set:
		return {}

	try:
		from ..providers.registry import build_model_manager

		mgr = build_model_manager(provider)
		all_models = mgr.list_managed_models()
	except Exception:
		return {}

	labels: dict[str, str] = {}
	for m in all_models:
		key = m.canonical_id or m.id
		if key in available_set and key not in labels:
			labels[key] = m.display_name

	return labels
