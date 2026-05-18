# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Literal, TypeAlias


ContextFacts: TypeAlias = dict[str, object]
PromptMetadata: TypeAlias = dict[str, object]

PromptSource = Literal["browser", "terminal", "generic", "image"]
BROWSER: Final[PromptSource] = "browser"
TERMINAL: Final[PromptSource] = "terminal"
GENERIC: Final[PromptSource] = "generic"
IMAGE_SOURCE: Final[PromptSource] = "image"


@dataclass(frozen=True, slots=True)
class ExtractionSnapshot:
	title: str
	appTitle: str
	text: str
	truncated: bool
	source: PromptSource = GENERIC


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
	source: PromptSource = GENERIC
	structure: ExtractionStructure | None = None


@dataclass(frozen=True, slots=True)
class ExtractionFacts:
	title: str | None = None
	app_title: str | None = None
	text: str | None = None
	truncated: bool | None = None
	structure: ExtractionStructure | None = None
	snapshot: ExtractionSnapshot | None = None


def build_extraction_facts_from_facts(facts: dict[str, Any]) -> ExtractionFacts | None:
	snapshot = facts.get("extraction_snapshot")
	extraction_text = facts.get("extraction_text")

	if not isinstance(snapshot, ExtractionSnapshot) and not isinstance(extraction_text, str):
		return None

	title: str | None = None
	app_title: str | None = None
	truncated: bool | None = None
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

	if isinstance(extraction_text, str):
		text = extraction_text

	if text is None:
		return None

	return ExtractionFacts(
		title=title,
		app_title=app_title,
		text=text,
		truncated=truncated,
		structure=structure,
		snapshot=snapshot if isinstance(snapshot, ExtractionSnapshot) else None,
	)


def build_extraction_result_from_facts(extraction_facts: ExtractionFacts | None) -> ExtractionResult | None:
	if extraction_facts is None:
		return None

	if extraction_facts.text is None:
		return None

	source = GENERIC
	if extraction_facts.snapshot is not None:
		source = extraction_facts.snapshot.source

	return ExtractionResult(
		title=extraction_facts.title or "",
		app_title=extraction_facts.app_title or "",
		text=extraction_facts.text,
		truncated=extraction_facts.truncated if extraction_facts.truncated is not None else False,
		source=source,
		structure=extraction_facts.structure,
	)


# ── Structured field selection ─────────────────────────────────────

StructuredField = Literal[
	"headings", "links", "buttons", "landmarks",
	"inputs", "comboboxes", "checkboxes", "radios",
]

ALL_STRUCTURED_FIELDS: tuple[StructuredField, ...] = (
	"headings", "links", "buttons", "landmarks",
	"inputs", "comboboxes", "checkboxes", "radios",
)

# Source type for image capture — mirrors image/services.py:CaptureSource.
ImageCaptureSource = Literal["foreground", "focus", "navigator", "desktop"]


# ── Content request types ──────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class PageTextRequest:
	"""Full text content of the current page/document."""

@dataclass(frozen=True, slots=True)
class PageStructureRequest:
	"""Structured semantic elements (headings, links, buttons, etc.)."""
	fields: tuple[StructuredField, ...] = ()  # () = all fields

@dataclass(frozen=True, slots=True)
class FocusedElementTextRequest:
	"""Text content of only the focused NVDA object."""

@dataclass(frozen=True, slots=True)
class ForegroundImageRequest:
	"""Screenshot of the foreground window."""

@dataclass(frozen=True, slots=True)
class FocusedElementImageRequest:
	"""Screenshot of the focused NVDA element."""

@dataclass(frozen=True, slots=True)
class NavigatorImageRequest:
	"""Screenshot of the NVDA navigator object."""


ContentRequest = (
	PageTextRequest | PageStructureRequest |
	FocusedElementTextRequest |
	ForegroundImageRequest | FocusedElementImageRequest | NavigatorImageRequest
)


@dataclass(frozen=True, slots=True)
class ExtractionIntent:
	"""What a use case wants the context pipeline to extract.

	Carries explicit ContentRequest objects.  The requests themselves
	document what data flows to the LLM — no convenience constructors,
	no hidden composition.
	"""
	requests: tuple[ContentRequest, ...] = ()


# ── Image capture snapshot (main-thread-safe) ──────────────────────

@dataclass(frozen=True, slots=True)
class ImageCaptureSnapshot:
	"""Raw image bytes captured on the NVDA main thread.

	Collectors read from this snapshot for preprocessing/encoding
	instead of calling NVDA APIs directly.  This enforces the invariant
	that only extractor-phase code runs on the main thread.
	"""
	raw_bytes: bytes
	source: ImageCaptureSource
	app_title: str | None = None
	window_title: str | None = None


# ── Output types ───────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class ImageContext:
	app_title: str | None = None
	window_title: str | None = None
	image_base64: str | None = None


@dataclass(frozen=True, slots=True)
class PromptContext:
	use_case_id: str
	facts: ContextFacts = field(default_factory=dict)
	extraction_facts: ExtractionFacts | None = None
	extraction_result: ExtractionResult | None = None
	text: str | None = None
	image_base64: str | None = None
	language: str | None = None
	metadata: PromptMetadata = field(default_factory=dict)
