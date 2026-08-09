# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class Part:
	type: Literal["text", "image", "tool_call", "tool_result"]
	text: str | None = None
	image: bytes | None = None
	tool_name: str | None = None
	tool_args: dict[str, Any] | None = None
	tool_result: dict[str, Any] | None = None
	tool_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class Tool:
	name: str
	description: str
	parameters: dict[str, Any] = field(default_factory=dict)
	required: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Message:
	role: Literal["user", "assistant", "system", "tool"]
	parts: tuple[Part, ...] = field(default_factory=tuple)
