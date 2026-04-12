# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from ..core.tooling import ToolCall
from .definition import ToolDefinition


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
