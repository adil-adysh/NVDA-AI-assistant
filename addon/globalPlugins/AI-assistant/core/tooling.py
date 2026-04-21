# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ToolArguments = dict[str, object]


@dataclass(slots=True)
class ToolCall:
	name: str
	arguments: ToolArguments
	id: str | None = None
