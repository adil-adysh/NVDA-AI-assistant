# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...core.canonical import Message
from ...core.message_transforms import build_assistant_message, build_user_message
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
		initial_image_base64: str | None = None,
		force_new: bool = False,
		seed_messages: tuple[Message, ...] | None = None,
	) -> str:
		"""Activate a conversation, seeding it with messages.

		When *seed_messages* is provided it is used verbatim (callers such as
		the presenter use it to seed a complete user-context + assistant-result
		conversation).  Otherwise the legacy *initial_* fields build the seeds.
		"""
		if seed_messages is None:
			seed_messages = self._build_seed_messages(initial_assistant_text, initial_image_base64)
		resolved_conversation_id = conversation_id
		if resolved_conversation_id is None and not force_new:
			resolved_conversation_id = self._chat_coordinator.get_active_conversation_id()
		return self._chat_coordinator.activate_conversation(
			conversation_id=resolved_conversation_id,
			seed_messages=seed_messages,
		)

	def add_user_context(
		self,
		*,
		content: str | None = None,
		image_base64: str | None = None,
	) -> str:
		"""Add a user/context message to the current conversation.

		The message is conversation context supplied by the user, never an
		assistant-generated answer.  If no active conversation exists yet it is
		created implicitly, matching the existing chat-opening semantics.
		"""
		if not content and not image_base64:
			return self.open_conversation()
		message = build_user_message(text=content, image_base64=image_base64)
		return self.open_conversation(seed_messages=(message,))

	def add_assistant_result(self, content: str) -> str:
		"""Add an assistant-generated result message to the current conversation."""
		if not content:
			return self.open_conversation()
		message = build_assistant_message(text=content)
		return self.open_conversation(seed_messages=(message,))

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

	def _build_seed_messages(self, initial_assistant_text: str | None, initial_image_base64: str | None = None) -> tuple[Any, ...]:
		messages: list[Any] = []
		if isinstance(initial_image_base64, str) and initial_image_base64.strip():
			messages.append(build_user_message(image_base64=initial_image_base64))
		if isinstance(initial_assistant_text, str) and initial_assistant_text.strip():
			messages.append(build_assistant_message(text=initial_assistant_text.strip()))
		return tuple(messages)
