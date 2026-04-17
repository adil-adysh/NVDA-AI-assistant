# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Final, Literal, TypeAlias


class SnapshotType(Enum):
	GENERIC = auto()
	PAGE = auto()
	EXCEL = auto()
	IMAGE = auto()


ContextProfile = Literal["app", "page", "image"]
APP: Final[ContextProfile] = "app"
PAGE: Final[ContextProfile] = "page"
IMAGE: Final[ContextProfile] = "image"
ContextProfileList: TypeAlias = tuple[ContextProfile, ...]


@dataclass(frozen=True, slots=True)
class ContentSnapshot:
	snapshot_type: SnapshotType
	title: str
	appTitle: str
	text: str
	truncated: bool
	headings: tuple[tuple[int | None, str], ...]
	links: tuple[str, ...]
	buttons: tuple[str, ...]
	landmarks: tuple[str, ...]
	metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExcelSnapshotMetadata:
	workbook: str | None = None
	worksheet: str | None = None
	cell_address: str | None = None
	range_address: str | None = None
	table_name: str | None = None
	formula: str | None = None
	cell_type: str | None = None
	note: str | None = None
	row_header: str | None = None
	column_header: str | None = None


PageSnapshot = ContentSnapshot


class ContextCollectionError(RuntimeError):
	pass


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
class PageFacts:
	title: str | None = None
	app_title: str | None = None
	text: str | None = None
	truncated: bool | None = None
	headings: tuple[tuple[int | None, str], ...] = ()
	links: tuple[str, ...] = ()
	buttons: tuple[str, ...] = ()
	landmarks: tuple[str, ...] = ()
	snapshot: PageSnapshot | None = None


def _normalize_str(value: Any) -> str:
	return value if isinstance(value, str) else ""


def _normalize_optional_bool(value: Any) -> bool | None:
	return value if isinstance(value, bool) else None


def _normalize_headings(value: Any) -> tuple[tuple[int | None, str], ...]:
	if not isinstance(value, tuple):
		return ()

	normalized: list[tuple[int | None, str]] = []
	for item in value:
		if not isinstance(item, tuple) or len(item) != 2:
			continue
		level, text = item
		if not (isinstance(level, int) or level is None):
			continue
		if not isinstance(text, str):
			continue
		normalized.append((level, text))

	return tuple(normalized)


def _normalize_str_tuple(value: Any) -> tuple[str, ...]:
	if not isinstance(value, tuple):
		return ()
	if not all(isinstance(item, str) for item in value):
		return ()
	return value


def build_page_facts_from_facts(facts: dict[str, Any]) -> PageFacts | None:
	snapshot = facts.get("page_snapshot")
	page_text = facts.get("page_text")
	if (
		not isinstance(snapshot, ContentSnapshot)
		and not isinstance(page_text, str)
		and not any(
			key in facts
			for key in (
				"page_title",
				"page_app_title",
				"page_truncated",
				"page_headings",
				"page_links",
				"page_buttons",
				"page_landmarks",
			)
		)
	):
		return None

	title: str | None = None
	app_title: str | None = None
	truncated: bool | None = None
	headings: tuple[tuple[int | None, str], ...] = ()
	links: tuple[str, ...] = ()
	buttons: tuple[str, ...] = ()
	landmarks: tuple[str, ...] = ()
	text: str | None = None

	if isinstance(snapshot, ContentSnapshot):
		title = snapshot.title
		app_title = snapshot.appTitle
		truncated = snapshot.truncated
		headings = snapshot.headings
		links = snapshot.links
		buttons = snapshot.buttons
		landmarks = snapshot.landmarks
		text = snapshot.text

	if isinstance(page_text, str):
		text = page_text

	if title is None:
		title = _normalize_str(facts.get("page_title")) or None
	if app_title is None:
		app_title = _normalize_str(facts.get("page_app_title")) or None
	if truncated is None:
		truncated = _normalize_optional_bool(facts.get("page_truncated"))
	if not headings:
		headings = _normalize_headings(facts.get("page_headings"))
	if not links:
		links = _normalize_str_tuple(facts.get("page_links"))
	if not buttons:
		buttons = _normalize_str_tuple(facts.get("page_buttons"))
	if not landmarks:
		landmarks = _normalize_str_tuple(facts.get("page_landmarks"))

	if text is None:
		return None

	return PageFacts(
		title=title,
		app_title=app_title,
		text=text,
		truncated=truncated,
		headings=headings,
		links=links,
		buttons=buttons,
		landmarks=landmarks,
		snapshot=snapshot if isinstance(snapshot, ContentSnapshot) else None,
	)


def build_page_context_from_facts(page_facts: PageFacts | None) -> PageContext | None:
	if page_facts is None:
		return None

	if page_facts.text is None:
		return None

	return PageContext(
		title=page_facts.title or "",
		app_title=page_facts.app_title or "",
		text=page_facts.text,
		truncated=page_facts.truncated if page_facts.truncated is not None else False,
		headings=page_facts.headings,
		links=page_facts.links,
		buttons=page_facts.buttons,
		landmarks=page_facts.landmarks,
	)


@dataclass(frozen=True, slots=True)
class ImageContext:
	app_title: str | None = None
	window_title: str | None = None
	image_base64: str | None = None


@dataclass(frozen=True, slots=True)
class PromptContext:
	use_case_id: str
	facts: dict[str, Any] = field(default_factory=dict)
	page_facts: PageFacts | None = None
	page_context: PageContext | None = None
	text: str | None = None
	image_base64: str | None = None
	metadata: dict[str, Any] = field(default_factory=dict)
