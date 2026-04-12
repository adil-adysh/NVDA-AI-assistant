# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from ..core.canonical import Tool
from ..core.tooling import ToolCall


def build_function_tool_definition(tool: Tool) -> dict[str, Any]:
	return {
		"type": "function",
		"function": {
			"name": tool.name,
			"description": tool.description,
			"parameters": tool.parameters,
		},
	}


def normalize_tool_calls(tool_calls: list[Any]) -> list[ToolCall] | None:
	calls: list[ToolCall] = []
	for item in tool_calls:
		if not isinstance(item, dict):
			continue
		if "function" in item and isinstance(item.get("function"), dict):
			function_payload = item["function"]
			name = str(function_payload.get("name", "")).strip()
			arguments = function_payload.get("arguments") if isinstance(function_payload.get("arguments"), dict) else {}
		elif "functionCall" in item and isinstance(item.get("functionCall"), dict):
			function_payload = item["functionCall"]
			name = str(function_payload.get("name", "")).strip()
			arguments = function_payload.get("args") if isinstance(function_payload.get("args"), dict) else {}
		else:
			name = str(item.get("name", "")).strip()
			arguments = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
		if not name:
			continue
		calls.append(ToolCall(name=name, arguments=arguments, id=item.get("id")))
	return calls or None
