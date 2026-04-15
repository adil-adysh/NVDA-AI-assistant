# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Sequence

from ...core.canonical import Message


@dataclass(slots=True)
class ConversationSession:
	_messages: list[Message] = field(default_factory=list)

	def snapshot(self) -> list[Message]:
		return list(self._messages)

	def append(self, message: Message) -> None:
		self._messages.append(message)

	def extend(self, messages: Sequence[Message]) -> None:
		self._messages.extend(messages)

	def reset(self) -> None:
		self._messages.clear()