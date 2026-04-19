# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..extractors.browser import BrowserAwarePageExtractor
from ...context.protocols import CollectorInput, ContextFragment
from ...context.types import APP, ContextCollectionError, ContextProfileList, PAGE, PageSnapshot


@dataclass(frozen=True, slots=True)
class PageTextCollector:
	extractor: BrowserAwarePageExtractor | None = None

	@property
	def profiles(self) -> ContextProfileList:
		return (APP, PAGE)

	def collect(self, input: CollectorInput) -> ContextFragment:
		if self.extractor is None:
			raise ContextCollectionError("PageTextCollector requires an extractor")

		snapshot = input.page_snapshot
		if not isinstance(snapshot, PageSnapshot):
			raise ContextCollectionError("PageTextCollector requires a page snapshot")

		return ContextFragment(
			facts={
				"page_text": snapshot.text,
				"page_snapshot": snapshot,
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
class PageStructureCollector:
	extractor: BrowserAwarePageExtractor | None = None

	@property
	def profiles(self) -> ContextProfileList:
		return (PAGE,)

	def collect(self, input: CollectorInput) -> ContextFragment:
		if self.extractor is None:
			raise ContextCollectionError("PageStructureCollector requires an extractor")

		snapshot = input.page_snapshot
		if not isinstance(snapshot, PageSnapshot):
			raise ContextCollectionError("PageStructureCollector requires a page snapshot")

		return ContextFragment(
			facts={
				"page_snapshot": snapshot,
				"page_title": snapshot.title,
				"page_app_title": snapshot.appTitle,
				"page_truncated": snapshot.truncated,
				"page_headings": snapshot.headings,
				"page_links": snapshot.links,
				"page_buttons": snapshot.buttons,
				"page_landmarks": snapshot.landmarks,
				"page_inputs": snapshot.inputs,
				"page_comboboxes": snapshot.comboboxes,
				"page_checkboxes": snapshot.checkboxes,
				"page_radios": snapshot.radios,
			},
			metadata={
				"use_case_id": input.use_case_id,
				"title": snapshot.title,
				"app_title": snapshot.appTitle,
				"truncated": snapshot.truncated,
			},
		)
