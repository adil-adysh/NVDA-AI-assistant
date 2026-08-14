# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass

from ..protocols import CollectorInput, PageContextFragment
from ..types import ContentRequest, ContextCollectionError, FocusedElementTextRequest


@dataclass(frozen=True, slots=True)
class FocusedTextCollector:
	"""Expose a pre-captured focused edit-box value to a use case."""

	always_collect = False

	def handles_request(self, request: ContentRequest) -> bool:
		return isinstance(request, FocusedElementTextRequest)

	def collect_for_request(
		self, _request: FocusedElementTextRequest, input_: CollectorInput
	) -> PageContextFragment:
		snapshot = input_.focused_text_snapshot
		if snapshot is None:
			raise ContextCollectionError("Focused text snapshot is unavailable")
		return PageContextFragment(
			facts={
				"focused_text": snapshot.text,
				"focused_text_snapshot": snapshot,
			},
			text=snapshot.text,
			metadata={
				"use_case_id": input_.use_case_id,
				"control_name": snapshot.control_name,
				"app_title": snapshot.app_title,
				"window_title": snapshot.window_title,
			},
		)
