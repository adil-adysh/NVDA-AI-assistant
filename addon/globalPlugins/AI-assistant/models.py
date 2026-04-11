# -*- coding: utf-8 -*-
from dataclasses import dataclass
from typing import Any, Callable, Literal


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    stage: Literal[
        "start",
        "collecting_context",
        "building_prompt",
        "llm_request",
        "streaming",
        "tool_execution",
        "complete",
        "error",
    ]
    message: str


ProgressHandler = Callable[[ProgressEvent], None]


@dataclass(frozen=True, slots=True)
class PageSnapshot:
    title: str
    appTitle: str
    text: str
    truncated: bool
    headings: tuple[tuple[int | None, str], ...]
    links: tuple[str, ...]
    buttons: tuple[str, ...]
    landmarks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SummaryResponse:
    text: str
    model: str
    provider: str = "unknown"
    metadata: dict[str, Any] | None = None


@dataclass(slots=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str | None = None


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Literal["user", "assistant", "system", "tool"]
    content: str | None = None
    image_base64: str | None = None
    tool_name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    model: str | None = None
    raw: Any | None = None
    metrics: Any | None = None
    tool_calls: list[ToolCall] | None = None
