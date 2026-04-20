# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .types import ContextProfileList, ExtractionSnapshot


@dataclass(frozen=True, slots=True)
class ContextFragment:
	facts: dict[str, Any] = field(default_factory=dict)
	text: str | None = None
	image_base64: str | None = None
	metadata: dict[str, Any] = field(default_factory=dict)


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
