# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
from typing import Any

from .canonical import Message, Part
from .messages import ChatMessage
from .tooling import ToolCall


def build_user_message(text: str | None = None, image_base64: str | None = None) -> Message:
	parts: list[Part] = []
	if text:
		parts.append(Part(type="text", text=text))
	if image_base64:
		try:
			parts.append(Part(type="image", image=base64.b64decode(image_base64)))
		except Exception as error:
			raise ValueError(f"Invalid image base64: {error}") from error
	return Message(role="user", parts=tuple(parts))


def build_assistant_message(text: str | None = None, tool_calls: list[ToolCall] | None = None) -> Message:
	parts: list[Part] = []
	if text:
		parts.append(Part(type="text", text=text))
	for tool_call in tool_calls or []:
		parts.append(
			Part(
				type="tool_call",
				tool_name=tool_call.name,
				tool_args=tool_call.arguments,
			)
		)
	return Message(role="assistant", parts=tuple(parts))


def build_tool_result_message(tool_name: str, content: str) -> Message:
	return Message(
		role="tool",
		parts=(
			Part(
				type="tool_result",
				text=content,
				tool_name=tool_name,
			),
		),
	)


def message_to_chat_message(message: Message) -> ChatMessage:
	text_parts: list[str] = []
	image_base64_text = None
	tool_name = None
	tool_calls: list[dict[str, Any]] = []

	for part in message.parts:
		if part.type == "text" and part.text is not None:
			text_parts.append(part.text)
		elif part.type == "image" and part.image is not None:
			image_base64_text = base64.b64encode(part.image).decode("ascii")
		elif part.type == "tool_call":
			tool_name = part.tool_name or tool_name
			tool_calls.append({"name": part.tool_name or "", "arguments": part.tool_args or {}})
		elif part.type == "tool_result":
			tool_name = part.tool_name or tool_name
			if part.tool_result is not None:
				text_parts.append(str(part.tool_result))
			elif part.text is not None:
				text_parts.append(part.text)

	return ChatMessage(
		role=message.role,
		content="\n".join(text_parts) if text_parts else None,
		image_base64=image_base64_text,
		tool_name=tool_name,
		tool_calls=tool_calls or None,
	)


def chat_messages_to_tool_results(tool_messages: list[ChatMessage]) -> list[Message]:
	canonical_messages: list[Message] = []
	for tool_message in tool_messages:
		if not isinstance(tool_message, ChatMessage):
			continue
		canonical_messages.append(
			Message(
				role="tool",
				parts=(
					Part(
						type="tool_result",
						text=tool_message.content,
						tool_name=tool_message.tool_name,
					),
				),
			)
		)
	return canonical_messages
