# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass

ToolArguments = dict[str, object]


@dataclass(slots=True)
class ToolCall:
	name: str
	arguments: ToolArguments
	id: str | None = None
