# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias


ContextProfile = Literal["app", "accessibility", "image"]
ContextProfileList: TypeAlias = tuple[ContextProfile, ...]


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
class PageContext:
	title: str
	app_title: str
	text: str
	truncated: bool
	headings: tuple[tuple[int | None, str], ...]
	links: tuple[str, ...]
	buttons: tuple[str, ...]
	landmarks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ImageContext:
	app_title: str | None = None
	window_title: str | None = None
	image_base64: str | None = None


@dataclass(frozen=True, slots=True)
class PromptContext:
	use_case_id: str
	facts: dict[str, Any] = field(default_factory=dict)
	text: str | None = None
	image_base64: str | None = None
	metadata: dict[str, Any] = field(default_factory=dict)
