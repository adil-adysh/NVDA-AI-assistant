# -*- coding: utf-8 -*-
from __future__ import annotations

from ..core.messages import ChatMessage
from ..core.tooling import ToolCall
from .registry import ToolRegistry


class ToolExecutor:
	def __init__(self, tool_registry: ToolRegistry) -> None:
		self._tool_registry = tool_registry

	def execute(self, tool_call: ToolCall) -> str:
		if tool_call.name not in self._tool_registry.get_tool_names():
			raise ValueError(f"Unknown tool: {tool_call.name}")
		try:
			return self._tool_registry.execute(tool_call)
		except Exception as error:
			raise RuntimeError(f"Tool '{tool_call.name}' execution failed: {error}") from error

	def execute_tool_calls(self, tool_calls: list[ToolCall]) -> list[ChatMessage]:
		tool_messages: list[ChatMessage] = []
		for tool_call in tool_calls:
			try:
				result = self.execute(tool_call)
			except Exception as error:
				result = f"Tool error: {error}"
			tool_messages.append(
				ChatMessage(
					role="tool",
					content=result,
					tool_name=tool_call.name,
				)
			)
		return tool_messages
