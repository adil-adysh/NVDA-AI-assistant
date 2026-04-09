# -*- coding: utf-8 -*-
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PageSnapshot:
    title: str
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
