# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .types import ContextProfileList, ExtractionSnapshot


@dataclass(frozen=True, slots=True)
class ContextFragment:
	"""Base data fragment returned by a collector."""
	facts: dict[str, Any] = field(default_factory=dict)
	text: str | None = None
	image_base64: str | None = None
	metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PageContextFragment(ContextFragment):
	"""Collector output for page-like content."""
	pass


@dataclass(frozen=True, slots=True)
class BrowserContextFragment(PageContextFragment):
	"""Collector output for browser page extraction."""
	pass


@dataclass(frozen=True, slots=True)
class TerminalContextFragment(PageContextFragment):
	"""Collector output for terminal/command transcript extraction."""
	pass


@dataclass(frozen=True, slots=True)
class ImageContextFragment(ContextFragment):
	"""Collector output for image-based extractions."""
	pass


@dataclass(frozen=True, slots=True)
class CollectorInput:
	use_case_id: str
	extraction_snapshot: ExtractionSnapshot | None = None


class ContextCollector(Protocol):
	@property
	def profiles(self) -> ContextProfileList:
		...

	def collect(self, input: CollectorInput) -> ContextFragment:
		...
