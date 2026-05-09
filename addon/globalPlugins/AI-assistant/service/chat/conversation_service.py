# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...core.message_transforms import build_assistant_message
from .coordinator import ChatCoordinator


@dataclass(frozen=True, slots=True)
class ConversationDeleteResult:
	deleted: bool
	active_conversation_deleted: bool
	active_conversation_id: str | None


class ConversationService:
	def __init__(self, chat_coordinator: ChatCoordinator) -> None:
		self._chat_coordinator = chat_coordinator

	def open_conversation(
		self,
		*,
		conversation_id: str | None = None,
		initial_assistant_text: str | None = None,
		force_new: bool = False,
	) -> str:
		seed_messages = self._build_seed_messages(initial_assistant_text)
		resolved_conversation_id = conversation_id
		if resolved_conversation_id is None and not force_new:
			resolved_conversation_id = self._chat_coordinator.get_active_conversation_id()
		return self._chat_coordinator.activate_conversation(
			conversation_id=resolved_conversation_id,
			seed_messages=seed_messages,
		)

	def current_conversation_id(self) -> str | None:
		return self._chat_coordinator.get_active_conversation_id()

	def history_transport(self) -> list[dict[str, Any]]:
		return self._chat_coordinator.get_history_transport()

	def list_conversation_summaries(self) -> list[dict[str, object]]:
		return [summary.to_metadata() for summary in self._chat_coordinator.list_conversations()]

	def delete_conversation(self, conversation_id: str) -> ConversationDeleteResult:
		active_conversation_id = self._chat_coordinator.get_active_conversation_id()
		deleted = self._chat_coordinator.delete_conversation(conversation_id)
		resolved_active_id = self._chat_coordinator.get_active_conversation_id()
		return ConversationDeleteResult(
			deleted=deleted,
			active_conversation_deleted=deleted and conversation_id == active_conversation_id,
			active_conversation_id=resolved_active_id,
		)

	def _build_seed_messages(self, initial_assistant_text: str | None) -> tuple[Any, ...]:
		if not isinstance(initial_assistant_text, str) or not initial_assistant_text.strip():
			return ()
		return (build_assistant_message(text=initial_assistant_text.strip()),)
