# -*- coding: utf-8 -*-
"""Built-in native tool catalog.

Kept free of NVDA imports so the catalog can be composed and tested outside a
running NVDA process.
"""
from __future__ import annotations

from datetime import datetime

from .definition import ToolAnnotations, ToolDefinition
from .registry import ToolRegistry


def _current_local_time(arguments: dict) -> str:
	return datetime.now().isoformat()


def build_default_tool_definitions() -> tuple[ToolDefinition, ...]:
	return (
		ToolDefinition(
			name="get_time",
			description="Get the current local date and time.",
			input_schema={"type": "object", "properties": {}, "additionalProperties": False},
			annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False),
			executor=_current_local_time,
		),
	)


def register_default_tools(tool_registry: ToolRegistry) -> None:
	for definition in build_default_tool_definitions():
		tool_registry.register_tool(definition)
