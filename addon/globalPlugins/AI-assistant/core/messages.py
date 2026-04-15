# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .tooling import ToolCall


@dataclass(frozen=True, slots=True)
class SummaryResponse:
	text: str
	model: str
	provider: str = "unknown"
	metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ChatMessage:
	role: Literal["user", "assistant", "system", "tool"]
	content: str | None = None
	image_base64: str | None = None
	tool_name: str | None = None
	tool_calls: list[dict[str, Any]] | None = None


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
	tool_name: str
	content: str


@dataclass(frozen=True, slots=True)
class LLMResponse:
	text: str
	model: str | None = None
	raw: Any | None = None
	metrics: Any | None = None
	tool_calls: list[ToolCall] | None = None
