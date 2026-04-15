# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass

from ...core.canonical import Message
from ...core.messages import LLMResponse


@dataclass(frozen=True, slots=True)
class ConversationTurnResult:
	response: LLMResponse
	messages: tuple[Message, ...]