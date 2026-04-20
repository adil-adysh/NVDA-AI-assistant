# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..extractors.base import TreeExtractor
from ...context.protocols import CollectorInput, ContextFragment
from ...context.types import APP, ContextCollectionError, ContextProfileList, PAGE, ExtractionSnapshot, ExtractionStructure


@dataclass(frozen=True, slots=True)
class ExtractionTextCollector:
	extractor: TreeExtractor | None = None

	@property
	def profiles(self) -> ContextProfileList:
		return (APP, PAGE)

	def collect(self, input: CollectorInput) -> ContextFragment:
		if self.extractor is None and input.extraction_snapshot is None:
			raise ContextCollectionError("ExtractionTextCollector requires an extraction snapshot or extractor")

		snapshot = input.extraction_snapshot
		if not isinstance(snapshot, ExtractionSnapshot):
			raise ContextCollectionError("ExtractionTextCollector requires an extraction snapshot")

		return ContextFragment(
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

	@property
	def profiles(self) -> ContextProfileList:
		return (PAGE,)

	def collect(self, input: CollectorInput) -> ContextFragment:
		if self.extractor is None and input.extraction_snapshot is None:
			raise ContextCollectionError("ExtractionStructureCollector requires an extraction snapshot or extractor")

		snapshot = input.extraction_snapshot
		if not isinstance(snapshot, ExtractionSnapshot):
			raise ContextCollectionError("ExtractionStructureCollector requires an extraction snapshot")

		page_structure = ExtractionStructure(
			headings=getattr(snapshot, "headings", ()),
			links=getattr(snapshot, "links", ()),
			buttons=getattr(snapshot, "buttons", ()),
			landmarks=getattr(snapshot, "landmarks", ()),
			inputs=getattr(snapshot, "inputs", ()),
			comboboxes=getattr(snapshot, "comboboxes", ()),
			checkboxes=getattr(snapshot, "checkboxes", ()),
			radios=getattr(snapshot, "radios", ()),
		)
		return ContextFragment(
			facts={
				"extraction_snapshot": snapshot,
				"extraction_title": snapshot.title,
				"extraction_app_title": snapshot.appTitle,
				"extraction_truncated": snapshot.truncated,
				"extraction_structure": page_structure,
				"extraction_headings": page_structure.headings,
				"extraction_links": page_structure.links,
				"extraction_buttons": page_structure.buttons,
				"extraction_landmarks": page_structure.landmarks,
				"extraction_inputs": page_structure.inputs,
				"extraction_comboboxes": page_structure.comboboxes,
				"extraction_checkboxes": page_structure.checkboxes,
				"extraction_radios": page_structure.radios,
			},
			metadata={
				"use_case_id": input.use_case_id,
				"title": snapshot.title,
				"app_title": snapshot.appTitle,
				"truncated": snapshot.truncated,
			},
		)
