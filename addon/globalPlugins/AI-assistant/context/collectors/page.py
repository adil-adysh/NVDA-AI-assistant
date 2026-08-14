# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass

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
	always_collect = False

	def handles_request(self, request: ContentRequest) -> bool:
		return isinstance(request, PageTextRequest)

	def collect_for_request(self, _request: PageTextRequest, input_: CollectorInput) -> PageContextFragment:
		snapshot = input_.extraction_snapshot
		if not isinstance(snapshot, ExtractionSnapshot):
			raise ContextCollectionError("ExtractionTextCollector requires an extraction snapshot")

		return PageContextFragment(
			facts={
				"extraction_text": snapshot.text,
				"extraction_snapshot": snapshot,
			},
			text=snapshot.text,
			metadata={
				"use_case_id": input_.use_case_id,
				"title": snapshot.title,
				"app_title": snapshot.appTitle,
				"truncated": snapshot.truncated,
			},
		)


@dataclass(frozen=True, slots=True)
class ExtractionStructureCollector:
	always_collect = False

	_STRUCTURED_ATTRS: tuple[StructuredField, ...] = ALL_STRUCTURED_FIELDS

	def handles_request(self, request: ContentRequest) -> bool:
		return isinstance(request, PageStructureRequest)

	def collect_for_request(self, request: PageStructureRequest, input_: CollectorInput) -> PageContextFragment:
		snapshot = self._require_snapshot(input_)
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
				"use_case_id": input_.use_case_id,
				"title": snapshot.title,
				"app_title": snapshot.appTitle,
				"truncated": snapshot.truncated,
			},
		)

	def _require_snapshot(self, input_: CollectorInput) -> ExtractionSnapshot:
		snapshot = input_.extraction_snapshot
		if not isinstance(snapshot, ExtractionSnapshot):
			raise ContextCollectionError(
				"ExtractionStructureCollector requires an extraction snapshot"
			)
		return snapshot
