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
class AddItemToChatAction:
	"""Add a single context/output item from a completed use case to the current conversation.

	``token`` references the stored result payload in ``ResultActionStore``;
	``item_id`` selects which context or output item inside that payload to add.
	"""

	token: str
	item_id: str


@dataclass(frozen=True, slots=True)
class OpenInNewChatAction:
	"""Create a new conversation carrying the complete use-case context and result.

	``token`` references the stored result payload in ``ResultActionStore``.
	"""

	token: str


UIAction = (
	ConversationNewAction
	| ConversationOpenAction
	| ConversationDeleteAction
	| AddItemToChatAction
	| OpenInNewChatAction
)


def serialize_ui_action(action: UIAction) -> tuple[str, dict[str, object]]:
	if isinstance(action, ConversationNewAction):
		return "conversation_new", {}
	if isinstance(action, ConversationOpenAction):
		return "conversation_open", {"conversation_id": action.conversation_id}
	if isinstance(action, ConversationDeleteAction):
		return "conversation_delete", {"conversation_id": action.conversation_id}
	if isinstance(action, AddItemToChatAction):
		return f"add_{action.item_id}_to_chat", _compact_payload(token=action.token)
	return "open_in_new_chat", _compact_payload(token=action.token)


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
	if action_id.startswith("add_") and action_id.endswith("_to_chat"):
		item_id = action_id[len("add_") : -len("_to_chat")]
		token = _read_non_empty_string(resolved_payload, "token")
		if token is None or not item_id:
			return None
		return AddItemToChatAction(token=token, item_id=item_id)
	if action_id == "open_in_new_chat":
		token = _read_non_empty_string(resolved_payload, "token")
		if token is None:
			return None
		return OpenInNewChatAction(token=token)
	return None


def _read_non_empty_string(payload: dict[str, Any], key: str) -> str | None:
	value = payload.get(key)
	if not isinstance(value, str):
		return None
	stripped_value = value.strip()
	return stripped_value or None


def _compact_payload(**kwargs: object) -> dict[str, object]:
	return {key: value for key, value in kwargs.items() if value is not None}
