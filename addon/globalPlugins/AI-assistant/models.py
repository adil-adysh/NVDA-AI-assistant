# -*- coding: utf-8 -*-
from dataclasses import dataclass
from typing import Any


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
