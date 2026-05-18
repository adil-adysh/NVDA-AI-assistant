# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass

from ..extractors.base import TreeExtractor
from ...context.protocols import CollectorInput, PageContextFragment
from ...context.types import (
	ALL_STRUCTURED_FIELDS,
	ContextCollectionError,
	ContentRequest,
	ExtractionSnapshot,
	PageStructureRequest,
	PageTextRequest,
	StructuredField,
)


def _field_value(snapshot: object, field: StructuredField) -> tuple[str, ...] | tuple[tuple[int | None, str], ...]:
	value = getattr(snapshot, field, ())
	return value if isinstance(value, tuple) else ()


@dataclass(frozen=True, slots=True)
class ExtractionTextCollector:
	extractor: TreeExtractor | None = None

	def handles_request(self, request: ContentRequest) -> bool:
		return isinstance(request, PageTextRequest)

	def collect_for_request(self, request: PageTextRequest, input: CollectorInput) -> PageContextFragment:
		if self.extractor is None and input.extraction_snapshot is None:
			raise ContextCollectionError("ExtractionTextCollector requires an extraction snapshot or extractor")

		snapshot = input.extraction_snapshot
		if not isinstance(snapshot, ExtractionSnapshot):
			raise ContextCollectionError("ExtractionTextCollector requires an extraction snapshot")

		return PageContextFragment(
			facts={
				"extraction_text": snapshot.text,
				"extraction_snapshot": snapshot,
			},
			text=snapshot.text,
			metadata={
				"use_case_id": input.use_case_id,
				"title": snapshot.title,
				"app_title": snapshot.appTitle,
				"truncated": snapshot.truncated,
			},
		)


@dataclass(frozen=True, slots=True)
class ExtractionStructureCollector:
	extractor: TreeExtractor | None = None

	_STRUCTURED_ATTRS: tuple[StructuredField, ...] = ALL_STRUCTURED_FIELDS

	def handles_request(self, request: ContentRequest) -> bool:
		return isinstance(request, PageStructureRequest)

	def collect_for_request(self, request: PageStructureRequest, input: CollectorInput) -> PageContextFragment:
		snapshot = self._require_snapshot(input)
		requested = set(request.fields) if request.fields else set(self._STRUCTURED_ATTRS)

		facts: dict[str, object] = {
			"extraction_snapshot": snapshot,
			"extraction_title": snapshot.title,
			"extraction_app_title": snapshot.appTitle,
			"extraction_truncated": snapshot.truncated,
		}

		for field in self._STRUCTURED_ATTRS:
			if field in requested:
				facts[f"extraction_{field}"] = _field_value(snapshot, field)

		return PageContextFragment(
			facts=facts,
			metadata={
				"use_case_id": input.use_case_id,
				"title": snapshot.title,
				"app_title": snapshot.appTitle,
				"truncated": snapshot.truncated,
			},
		)

	def _require_snapshot(self, input: CollectorInput) -> ExtractionSnapshot:
		if self.extractor is None and input.extraction_snapshot is None:
			raise ContextCollectionError(
				"ExtractionStructureCollector requires an extraction snapshot or extractor"
			)
		snapshot = input.extraction_snapshot
		if not isinstance(snapshot, ExtractionSnapshot):
			raise ContextCollectionError(
				"ExtractionStructureCollector requires an extraction snapshot"
			)
		return snapshot
