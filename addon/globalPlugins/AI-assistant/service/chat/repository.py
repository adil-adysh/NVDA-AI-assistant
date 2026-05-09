# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from ...core.canonical import Message
from .session import ConversationSession


class ConversationRepository(Protocol):
	def exists(self, conversation_id: str) -> bool:
		...

	def load(self, conversation_id: str) -> ConversationSession:
		...

	def save(self, conversation_id: str, messages: Sequence[Message]) -> None:
		...

	def list_summaries(self) -> list["ConversationSummary"]:
		...

	def delete(self, conversation_id: str) -> bool:
		...


@dataclass(frozen=True, slots=True)
class ConversationSummary:
	conversation_id: str
	title: str
	preview: str
	message_count: int
	updated_at: float

	def to_metadata(self) -> dict[str, Any]:
		return {
			"id": self.conversation_id,
			"title": self.title,
			"preview": self.preview,
			"message_count": self.message_count,
			"updated_at": self.updated_at,
		}
