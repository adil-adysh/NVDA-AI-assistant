# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Callable, Sequence, TypeVar

from .protocols import CollectorInput, ContextCollector, ContextFragment
from .types import (
	ContentSnapshot,
	ContextCollectionError,
	ContextProfileList,
	PageContext,
	PageFacts,
	PageSnapshot,
	PAGE,
	PromptContext,
	build_page_context_from_facts,
	build_page_facts_from_facts,
)

T = TypeVar("T")
MainThreadExecutor = Callable[[Callable[..., T]], T]


class ContextPipeline:
	def __init__(self, collectors: Sequence[ContextCollector], main_thread_executor: MainThreadExecutor) -> None:
		self._collectors = tuple(collectors)
		self._main_thread_executor = main_thread_executor

	def collect(self, use_case_id: str, context_profile: ContextProfileList, **kwargs: Any) -> PromptContext:
		if not context_profile:
			return PromptContext(use_case_id=use_case_id, metadata={"context_profile": context_profile})

		shared_snapshot = self._resolve_shared_snapshot(context_profile, kwargs)
		if PAGE in context_profile and shared_snapshot is None:
			raise ContextCollectionError("Unable to obtain page snapshot for page context")

		collector_input = CollectorInput(use_case_id=use_case_id, snapshot=shared_snapshot)
		merged_facts: dict[str, Any] = {}
		merged_metadata: dict[str, Any] = {"context_profile": context_profile}
		text_parts: list[str] = []
		image_base64: str | None = None

		for collector in self._collectors:
			if not set(collector.profiles).intersection(context_profile):
				continue
			fragment = collector.collect(collector_input)
			merged_facts.update(fragment.facts)
			merged_metadata.update(fragment.metadata)
			if fragment.text:
				text_parts.append(fragment.text)
			if fragment.image_base64 is not None:
				image_base64 = fragment.image_base64

		page_facts = build_page_facts_from_facts(merged_facts)
		page_context = build_page_context_from_facts(page_facts)

		return PromptContext(
			use_case_id=use_case_id,
			facts=merged_facts,
			page_facts=page_facts,
			page_context=page_context,
			text="\n\n".join(part for part in text_parts if part),
			image_base64=image_base64,
			metadata=merged_metadata,
		)

	def _resolve_shared_snapshot(self, context_profile: ContextProfileList, kwargs: dict[str, Any]) -> PageSnapshot | None:
		snapshot = kwargs.get("snapshot")
		if isinstance(snapshot, PageSnapshot):
			return snapshot

		for collector in self._collectors:
			if not set(collector.profiles).intersection(context_profile):
				continue
			extractor = getattr(collector, "extractor", None)
			if extractor is None:
				continue
			try:
				snapshot = self._main_thread_executor(extractor.extract)
			except Exception:
				continue
			if isinstance(snapshot, PageSnapshot):
				return snapshot
		return None
