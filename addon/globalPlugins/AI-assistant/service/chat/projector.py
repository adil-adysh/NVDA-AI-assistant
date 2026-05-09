# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ...core.canonical import Message
from ...core.message_transforms import message_to_chat_message
from ...core.messages import ChatMessage


def project_chat_history(messages: Sequence[Message]) -> list[ChatMessage]:
	return [message_to_chat_message(message) for message in messages]


def project_chat_history_transport(messages: Sequence[Message]) -> list[dict[str, Any]]:
	projected_messages: list[dict[str, Any]] = []
	for index, message in enumerate(project_chat_history(messages)):
		content: list[dict[str, Any]] = []
		if isinstance(message.content, str) and message.content.strip():
			content.append({"type": "text", "text": message.content})
		if isinstance(message.image_base64, str) and message.image_base64.strip():
			content.append(
				{
					"type": "image",
					"image_base64": message.image_base64,
					"mime_type": "image/png",
					"alt": "[Image attachment included]",
				}
			)
		if not content:
			continue
		projected_messages.append(
			{
				"id": f"history-{index}",
				"role": message.role,
				"content": content,
			}
		)
	return projected_messages
