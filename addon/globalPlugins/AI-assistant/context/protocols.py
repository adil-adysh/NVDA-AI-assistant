# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .types import ContentRequest, ExtractionSnapshot, ImageCaptureSnapshot, ImageCaptureSource


ContextFacts = dict[str, object]
PromptMetadata = dict[str, object]


@dataclass(frozen=True, slots=True)
class ContextFragment:
	"""Base data fragment returned by a collector."""
	facts: ContextFacts = field(default_factory=dict)
	text: str | None = None
	image_base64: str | None = None
	metadata: PromptMetadata = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PageContextFragment(ContextFragment):
	"""Collector output for page-like content."""


@dataclass(frozen=True, slots=True)
class BrowserContextFragment(PageContextFragment):
	"""Collector output for browser page extraction."""


@dataclass(frozen=True, slots=True)
class TerminalContextFragment(PageContextFragment):
	"""Collector output for terminal/command transcript extraction."""


@dataclass(frozen=True, slots=True)
class ImageContextFragment(ContextFragment):
	"""Collector output for image-based extractions."""


@dataclass(frozen=True, slots=True)
class CollectorInput:
	use_case_id: str
	extraction_snapshot: ExtractionSnapshot | None = None
	# Image snapshots captured on the main thread, keyed by source.
	image_snapshots: dict[ImageCaptureSource, ImageCaptureSnapshot] = field(default_factory=dict)


class ContextCollector(Protocol):
	def handles_request(self, request: ContentRequest) -> bool:
		...

	def collect_for_request(self, request: ContentRequest, input_: CollectorInput) -> ContextFragment:
		...
