# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import json
from typing import Any

from .canonical import Message, Part
from .messages import ChatMessage
from .tooling import ToolCall, ToolExecutionResult


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
				tool_call_id=tool_call.id,
			)
		)
	return Message(role="assistant", parts=tuple(parts))


def build_tool_result_message(
	tool_name: str,
	content: str,
	tool_call_id: str | None = None,
) -> Message:
	"""Build a legacy text-only tool result message."""
	return Message(
		role="tool",
		parts=(
			Part(
				type="tool_result",
				text=content,
				tool_name=tool_name,
				tool_call_id=tool_call_id,
			),
		),
	)


def build_tool_result_message_from_result(result: ToolExecutionResult) -> Message:
	"""Build a canonical tool result carrying bounded text and structured data.

	``Part.text`` is the bounded, provider-safe rendering; ``Part.tool_result``
	retains the full structured envelope for persistence and diagnostics.
	"""
	return Message(
		role="tool",
		parts=(
			Part(
				type="tool_result",
				text=result.to_model_text(),
				tool_name=result.tool_name,
				tool_call_id=result.tool_call_id,
				tool_result=result.to_dict(),
			),
		),
	)


def tool_result_message_from_payload(payload: dict[str, Any]) -> ToolExecutionResult | None:
	"""Reload a structured result from persisted history when available."""
	if not isinstance(payload, dict) or "ok" not in payload:
		return None
	try:
		return ToolExecutionResult.from_dict(payload)
	except (TypeError, ValueError):
		return None


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
			rendered = render_tool_result_text(part)
			if rendered:
				text_parts.append(rendered)

	return ChatMessage(
		role=message.role,
		content="\n".join(text_parts) if text_parts else None,
		image_base64=image_base64_text,
		tool_name=tool_name,
		tool_calls=tool_calls or None,
	)


def render_tool_result_text(part: Part) -> str:
	"""Return model/UI-visible text for a tool-result part.

	Bounded text wins; legacy or externally constructed parts fall back to a
	deterministic JSON rendering of structured content.
	"""
	if part.text is not None:
		return part.text
	if part.tool_result is None:
		return ""
	if isinstance(part.tool_result, str):
		return part.tool_result
	try:
		return json.dumps(part.tool_result, ensure_ascii=False, sort_keys=True)
	except (TypeError, ValueError):
		return str(part.tool_result)


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
