# -*- coding: utf-8 -*-
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional
from collections.abc import Callable


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


class TaskType(str, Enum):
    SUMMARY = "summary"
    IMAGE_DESCRIPTION = "image_description"


@dataclass(frozen=True, slots=True)
class LLMRequest:
    task_type: TaskType
    input_text: str | None = None
    image_base64: str | None = None
    stream: bool = False
    stream_handler: Callable[[str], None] | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    model: str | None = None
    raw: Any | None = None
    metrics: Any | None = None
