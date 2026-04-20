# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Literal, TypeAlias


ContextProfile = Literal["app", "page", "image"]
APP: Final[ContextProfile] = "app"
PAGE: Final[ContextProfile] = "page"
IMAGE: Final[ContextProfile] = "image"
ContextProfileList: TypeAlias = tuple[ContextProfile, ...]


@dataclass(frozen=True, slots=True)
class ExtractionSnapshot:
	title: str
	appTitle: str
	text: str
	truncated: bool


@dataclass(frozen=True, slots=True)
class BrowserExtractionSnapshot(ExtractionSnapshot):
	headings: tuple[tuple[int | None, str], ...] = ()
	links: tuple[str, ...] = ()
	buttons: tuple[str, ...] = ()
	landmarks: tuple[str, ...] = ()
	inputs: tuple[str, ...] = ()
	comboboxes: tuple[str, ...] = ()
	checkboxes: tuple[str, ...] = ()
	radios: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExtractionStructure:
	headings: tuple[tuple[int | None, str], ...] = ()
	links: tuple[str, ...] = ()
	buttons: tuple[str, ...] = ()
	landmarks: tuple[str, ...] = ()
	inputs: tuple[str, ...] = ()
	comboboxes: tuple[str, ...] = ()
	checkboxes: tuple[str, ...] = ()
	radios: tuple[str, ...] = ()


class ContextCollectionError(RuntimeError):
	pass


@dataclass(frozen=True, slots=True)
class ExtractionResult:
	title: str
	app_title: str
	text: str
	truncated: bool
	structure: ExtractionStructure | None = None


@dataclass(frozen=True, slots=True)
class ExtractionFacts:
	title: str | None = None
	app_title: str | None = None
	text: str | None = None
	truncated: bool | None = None
	structure: ExtractionStructure | None = None
	snapshot: ExtractionSnapshot | None = None


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


def build_extraction_facts_from_facts(facts: dict[str, Any]) -> ExtractionFacts | None:
	snapshot = facts.get("extraction_snapshot") if "extraction_snapshot" in facts else facts.get("page_snapshot")
	page_text = facts.get("extraction_text") if "extraction_text" in facts else facts.get("page_text")
	if (
		not isinstance(snapshot, ExtractionSnapshot)
		and not isinstance(page_text, str)
		and not any(
			key in facts
			for key in (
				"extraction_title",
				"page_title",
				"extraction_app_title",
				"page_app_title",
				"extraction_truncated",
				"page_truncated",
				"extraction_headings",
				"page_headings",
				"extraction_links",
				"page_links",
				"extraction_buttons",
				"page_buttons",
				"extraction_landmarks",
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
	inputs: tuple[str, ...] = ()
	comboboxes: tuple[str, ...] = ()
	checkboxes: tuple[str, ...] = ()
	radios: tuple[str, ...] = ()
	text: str | None = None

	structure: ExtractionStructure | None = None

	if isinstance(snapshot, ExtractionSnapshot):
		title = snapshot.title
		app_title = snapshot.appTitle
		truncated = snapshot.truncated
		text = snapshot.text
		if isinstance(snapshot, BrowserExtractionSnapshot):
			structure = ExtractionStructure(
				headings=snapshot.headings,
				links=snapshot.links,
				buttons=snapshot.buttons,
				landmarks=snapshot.landmarks,
				inputs=snapshot.inputs,
				comboboxes=snapshot.comboboxes,
				checkboxes=snapshot.checkboxes,
				radios=snapshot.radios,
			)

	if isinstance(page_text, str):
		text = page_text

	if title is None:
		title = _normalize_str(facts.get("page_title")) or None
	if app_title is None:
		app_title = _normalize_str(facts.get("page_app_title")) or None
	if truncated is None:
		truncated = _normalize_optional_bool(facts.get("page_truncated"))
	page_structure = facts.get("extraction_structure") if "extraction_structure" in facts else facts.get("page_structure")
	if page_structure is None:
		headings = _normalize_headings(facts.get("extraction_headings") if "extraction_headings" in facts else facts.get("page_headings"))
		links = _normalize_str_tuple(facts.get("extraction_links") if "extraction_links" in facts else facts.get("page_links"))
		buttons = _normalize_str_tuple(facts.get("extraction_buttons") if "extraction_buttons" in facts else facts.get("page_buttons"))
		landmarks = _normalize_str_tuple(facts.get("extraction_landmarks") if "extraction_landmarks" in facts else facts.get("page_landmarks"))
		inputs = _normalize_str_tuple(facts.get("extraction_inputs") if "extraction_inputs" in facts else facts.get("page_inputs"))
		comboboxes = _normalize_str_tuple(facts.get("extraction_comboboxes") if "extraction_comboboxes" in facts else facts.get("page_comboboxes"))
		checkboxes = _normalize_str_tuple(facts.get("extraction_checkboxes") if "extraction_checkboxes" in facts else facts.get("page_checkboxes"))
		radios = _normalize_str_tuple(facts.get("extraction_radios") if "extraction_radios" in facts else facts.get("page_radios"))
		if any((headings, links, buttons, landmarks, inputs, comboboxes, checkboxes, radios)):
			page_structure = ExtractionStructure(
				headings=headings,
				links=links,
				buttons=buttons,
				landmarks=landmarks,
				inputs=inputs,
				comboboxes=comboboxes,
				checkboxes=checkboxes,
				radios=radios,
			)

	if text is None:
		return None

	return ExtractionFacts(
		title=title,
		app_title=app_title,
		text=text,
		truncated=truncated,
		structure=page_structure if isinstance(page_structure, ExtractionStructure) else None,
		snapshot=snapshot if isinstance(snapshot, ExtractionSnapshot) else None,
	)


def build_extraction_result_from_facts(extraction_facts: ExtractionFacts | None) -> ExtractionResult | None:
	if extraction_facts is None:
		return None

	if extraction_facts.text is None:
		return None

	return ExtractionResult(
		title=extraction_facts.title or "",
		app_title=extraction_facts.app_title or "",
		text=extraction_facts.text,
		truncated=extraction_facts.truncated if extraction_facts.truncated is not None else False,
		structure=extraction_facts.structure,
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
	extraction_facts: ExtractionFacts | None = None
	extraction_result: ExtractionResult | None = None
	text: str | None = None
	image_base64: str | None = None
	metadata: dict[str, Any] = field(default_factory=dict)
