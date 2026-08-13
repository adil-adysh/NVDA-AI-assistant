# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass

from ...core.canonical import Message


@dataclass(frozen=True, slots=True)
class ChatTurnTransaction:
	prior_messages: tuple[Message, ...]
	staged_messages: tuple[Message, ...]
	transient_context_messages: tuple[Message, ...] = ()

	def request_messages(self) -> list[Message]:
		return [*self.prior_messages, *self.transient_context_messages, *self.staged_messages]

	def committed_messages(self, generated_messages: tuple[Message, ...]) -> tuple[Message, ...]:
		return (*self.staged_messages, *generated_messages)
