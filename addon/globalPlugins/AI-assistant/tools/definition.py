# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any

ToolParameters = dict[str, object]
ToolArguments = dict[str, object]
ToolExecutorCallable = Callable[[ToolArguments], str]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
	name: str
	description: str
	parameters: ToolParameters = field(default_factory=dict)
	required: list[str] = field(default_factory=list)
	executor: ToolExecutorCallable | None = None

	def to_dict(self) -> dict[str, object]:
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
