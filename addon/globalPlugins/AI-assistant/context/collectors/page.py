# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..extractors.browser import BrowserAwarePageExtractor
from ...context.protocols import ContextFragment
from ...context.types import ContextProfileList, PageContext


@dataclass(frozen=True, slots=True)
class PageContextCollector:
	extractor: BrowserAwarePageExtractor | None = None

	@property
	def profiles(self) -> ContextProfileList:
		return ("app", "accessibility")

	def collect(self, use_case_id: str, **kwargs: Any) -> ContextFragment:
		if self.extractor is None:
			raise ValueError("PageContextCollector requires an extractor")

		snapshot = self.extractor.extract()
		page_context = PageContext(
			title=snapshot.title,
			app_title=snapshot.appTitle,
			text=snapshot.text,
			truncated=snapshot.truncated,
			headings=snapshot.headings,
			links=snapshot.links,
			buttons=snapshot.buttons,
			landmarks=snapshot.landmarks,
		)
		return ContextFragment(
			facts={
				"page_context": page_context,
				"page_snapshot": snapshot,
			},
			text=snapshot.text,
			metadata={
				"use_case_id": use_case_id,
				"title": snapshot.title,
				"app_title": snapshot.appTitle,
				"truncated": snapshot.truncated,
			},
		)
