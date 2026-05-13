# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ConversationNewAction:
	pass


@dataclass(frozen=True, slots=True)
class ConversationOpenAction:
	conversation_id: str


@dataclass(frozen=True, slots=True)
class ConversationDeleteAction:
	conversation_id: str


@dataclass(frozen=True, slots=True)
class OpenChatAction:
	token: str | None = None
	assistant_seed_text: str | None = None
	initial_image_base64: str | None = None
	force_new_conversation: bool = False


@dataclass(frozen=True, slots=True)
class AttachToCurrentAction:
	"""Open chat attached to the current conversation — no seed text, no token cost."""
	pass


UIAction = ConversationNewAction | ConversationOpenAction | ConversationDeleteAction | OpenChatAction | AttachToCurrentAction


def serialize_ui_action(action: UIAction) -> tuple[str, dict[str, object]]:
	if isinstance(action, ConversationNewAction):
		return "conversation_new", {}
	if isinstance(action, ConversationOpenAction):
		return "conversation_open", {"conversation_id": action.conversation_id}
	if isinstance(action, ConversationDeleteAction):
		return "conversation_delete", {"conversation_id": action.conversation_id}
	if isinstance(action, AttachToCurrentAction):
		return "attach_to_current", {}
	return "open_chat", _compact_payload(
		token=action.token,
		assistant_seed_text=action.assistant_seed_text,
		initial_image_base64=action.initial_image_base64,
		force_new_conversation=True if action.force_new_conversation else None,
	)


def parse_ui_action(action_id: str, payload: dict[str, Any] | None) -> UIAction | None:
	resolved_payload = payload if isinstance(payload, dict) else {}
	if action_id == "conversation_new":
		return ConversationNewAction()
	if action_id == "conversation_open":
		conversation_id = _read_non_empty_string(resolved_payload, "conversation_id")
		if conversation_id is None:
			return None
		return ConversationOpenAction(conversation_id=conversation_id)
	if action_id == "conversation_delete":
		conversation_id = _read_non_empty_string(resolved_payload, "conversation_id")
		if conversation_id is None:
			return None
		return ConversationDeleteAction(conversation_id=conversation_id)
	if action_id == "attach_to_current":
		return AttachToCurrentAction()
	if action_id == "open_chat":
		return OpenChatAction(
			token=_read_non_empty_string(resolved_payload, "token"),
			assistant_seed_text=_read_non_empty_string(resolved_payload, "assistant_seed_text"),
			initial_image_base64=_read_non_empty_string(resolved_payload, "initial_image_base64"),
			force_new_conversation=resolved_payload.get("force_new_conversation") is True,
		)
	return None


def _read_non_empty_string(payload: dict[str, Any], key: str) -> str | None:
	value = payload.get(key)
	if not isinstance(value, str):
		return None
	stripped_value = value.strip()
	return stripped_value or None


def _compact_payload(**kwargs: object) -> dict[str, object]:
	return {key: value for key, value in kwargs.items() if value is not None}
