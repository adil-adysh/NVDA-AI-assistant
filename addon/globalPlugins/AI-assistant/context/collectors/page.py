# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..extractors.base import BasePageExtractor
from ...context.protocols import CollectorInput, ContextFragment
from ...context.types import APP, ContentSnapshot, ContextCollectionError, ContextProfileList, PAGE


@dataclass(frozen=True, slots=True)
class PageTextCollector:
	extractor: BasePageExtractor | None = None

	@property
	def profiles(self) -> ContextProfileList:
		return (APP, PAGE)

	def collect(self, input: CollectorInput) -> ContextFragment:
		if self.extractor is None:
			raise ContextCollectionError("PageTextCollector requires an extractor")

		snapshot = input.snapshot
		if not isinstance(snapshot, ContentSnapshot):
			raise ContextCollectionError("PageTextCollector requires a content snapshot")

		return ContextFragment(
			facts={
				"content_text": snapshot.text,
				"content_snapshot": snapshot,
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
	extractor: BasePageExtractor | None = None

	@property
	def profiles(self) -> ContextProfileList:
		return (PAGE,)

	def collect(self, input: CollectorInput) -> ContextFragment:
		if self.extractor is None:
			raise ContextCollectionError("PageStructureCollector requires an extractor")

		snapshot = input.snapshot
		if not isinstance(snapshot, ContentSnapshot):
			raise ContextCollectionError("PageStructureCollector requires a content snapshot")

		return ContextFragment(
			facts={
				"content_snapshot": snapshot,
				"content_title": snapshot.title,
				"content_app_title": snapshot.appTitle,
				"content_truncated": snapshot.truncated,
				"page_headings": snapshot.headings,
				"page_links": snapshot.links,
				"page_buttons": snapshot.buttons,
				"page_landmarks": snapshot.landmarks,
			},
			metadata={
				"use_case_id": input.use_case_id,
				"title": snapshot.title,
				"app_title": snapshot.appTitle,
				"truncated": snapshot.truncated,
			},
		)
