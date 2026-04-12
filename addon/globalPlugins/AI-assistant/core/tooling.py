# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ToolCall:
	name: str
	arguments: dict[str, Any]
	id: str | None = None
