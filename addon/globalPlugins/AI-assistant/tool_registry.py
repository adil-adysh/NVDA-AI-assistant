# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any

from .models import ToolCall

ToolExecutor = Callable[[dict[str, Any]], str]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
	name: str
	description: str
	parameters: dict[str, Any] = field(default_factory=dict)
	required: list[str] = field(default_factory=list)
	executor: ToolExecutor | None = None

	def to_dict(self) -> dict[str, Any]:
		return {
			"type": "function",
			"function": {
				"name": self.name,
				"description": self.description,
				"parameters": {
					"type": "object",
					"properties": self.parameters,
					"required": self.required,
				},
			},
		}


class ToolRegistry:
	"""Registry for tool definitions and execution handlers."""

	def __init__(self) -> None:
		self._tools: dict[str, ToolDefinition] = {}

	def register_tool(self, tool: ToolDefinition) -> None:
		name = tool.name.strip()
		if not name:
			raise ValueError("Tool name is required")
		if name in self._tools:
			raise ValueError(f"Tool already registered: {name}")
		if tool.executor is None:
			raise ValueError("Tool executor is required")
		self._tools[name] = tool

	def get_definitions(self) -> list[dict[str, Any]]:
		return [tool.to_dict() for tool in self._tools.values()]

	def get_tool_names(self) -> list[str]:
		return list(self._tools.keys())

	def execute(self, tool_call: ToolCall) -> str:
		if tool_call.name not in self._tools:
			raise ValueError(f"Unknown tool: {tool_call.name}")
		tool = self._tools[tool_call.name]
		try:
			return tool.executor(tool_call.arguments or {})
		except Exception as error:
			raise RuntimeError(f"Tool '{tool.name}' execution failed: {error}") from error
