# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Sequence

from ...core.canonical import Message
from ...core.message_transforms import message_to_chat_message
from ...core.messages import ChatMessage


def project_chat_history(messages: Sequence[Message]) -> list[ChatMessage]:
	return [message_to_chat_message(message) for message in messages]