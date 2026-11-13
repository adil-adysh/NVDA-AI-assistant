# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from typing import Any

from ..core.canonical import Tool
from ..core.tooling import ToolCall
from .schema import clone_schema


def build_function_tool_definition(tool: Tool) -> dict[str, object]:
	"""Serialize a canonical tool for OpenAI-compatible and Ollama endpoints.

	The full input schema is preserved; ``parameters``/``required`` are used
	only when a legacy caller omitted ``input_schema``.
	"""
	schema = tool.input_schema
	if not isinstance(schema, dict):
		schema = {
			"type": "object",
			"properties": clone_schema(tool.parameters),
			"required": list(tool.required),
		}
		if not schema["required"]:
			schema.pop("required")
	return {
		"type": "function",
		"function": {
			"name": tool.name,
			"description": tool.description,
			"parameters": clone_schema(schema),
		},
	}


def normalize_tool_calls(tool_calls: list[Any]) -> list[ToolCall] | None:
	"""Normalize provider tool-call payloads without hiding malformed JSON.

	Malformed argument JSON produces a ``ToolCall`` with ``parse_error`` set
	(and empty arguments) so the executor can refuse to run it with an
	actionable error instead of silently executing ``{}``.
	"""
	calls: list[ToolCall] = []
	for item in tool_calls:
		if not isinstance(item, dict):
			continue
		parse_error: str | None = None
		raw_arguments: str | None = None
		if "function" in item and isinstance(item.get("function"), dict):
			function_payload = item["function"]
			name = str(function_payload.get("name", "")).strip()
			raw_arguments_value = function_payload.get("arguments")
			arguments, parse_error, raw_arguments = _decode_arguments(raw_arguments_value)
		elif "functionCall" in item and isinstance(item.get("functionCall"), dict):
			function_payload = item["functionCall"]
			name = str(function_payload.get("name", "")).strip()
			args_value = function_payload.get("args")
			arguments = dict(args_value) if isinstance(args_value, dict) else {}
		else:
			name = str(item.get("name", "")).strip()
			arguments, parse_error, raw_arguments = _decode_arguments(item.get("arguments"))
		if not name:
			continue
		calls.append(
			ToolCall(
				name=name,
				arguments=arguments,
				id=item.get("id"),
				parse_error=parse_error,
				raw_arguments=raw_arguments,
			)
		)
	return calls or None


def _decode_arguments(value: Any) -> tuple[dict[str, Any], str | None, str | None]:
	if isinstance(value, dict):
		return dict(value), None, None
	if value is None or value == "":
		return {}, None, None
	if isinstance(value, str):
		try:
			parsed = json.loads(value)
		except json.JSONDecodeError as error:
			return {}, f"malformed JSON arguments: {error.msg} at position {error.pos}", value
		if isinstance(parsed, dict):
			return parsed, None, value
		return {}, f"arguments must decode to a JSON object, got {type(parsed).__name__}", value
	return {}, f"unsupported arguments payload type {type(value).__name__}", None
