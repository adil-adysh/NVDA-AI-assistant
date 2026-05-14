# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Callable, Sequence, TypeVar

from .protocols import CollectorInput, ContextCollector
from .types import (
	ContextCollectionError,
	ContextFacts,
	ExtractionIntent,
	ExtractionSnapshot,
	PageTextRequest,
	PromptContext,
	PromptMetadata,
	build_extraction_result_from_facts,
	build_extraction_facts_from_facts,
)

T = TypeVar("T")
MainThreadExecutor = Callable[[Callable[..., T]], T]


class ContextPipeline:
	def __init__(self, collectors: Sequence[ContextCollector], main_thread_executor: MainThreadExecutor) -> None:
		self._collectors = tuple(collectors)
		self._main_thread_executor = main_thread_executor

	def collect(self, use_case_id: str, extraction_intent: ExtractionIntent, **kwargs: Any) -> PromptContext:
		if not extraction_intent.requests:
			return PromptContext(use_case_id=use_case_id, metadata={})

		shared_snapshot = self._resolve_shared_extraction_snapshot(extraction_intent, kwargs)
		if self._needs_page_text(extraction_intent) and shared_snapshot is None:
			raise ContextCollectionError("Unable to obtain page snapshot for requested text extraction")

		collector_input = CollectorInput(use_case_id=use_case_id, extraction_snapshot=shared_snapshot)
		merged_facts: ContextFacts = {}
		merged_metadata: PromptMetadata = {}
		text_parts: list[str] = []
		image_base64: str | None = None

		for request in extraction_intent.requests:
			for collector in self._collectors:
				handler = getattr(collector, "handles_request", None)
				if handler is None or not handler(request):
					continue
				fragment = collector.collect_for_request(request, collector_input)
				merged_facts.update(fragment.facts)
				merged_metadata.update(fragment.metadata)
				if fragment.text:
					text_parts.append(fragment.text)
				if fragment.image_base64 is not None:
					image_base64 = fragment.image_base64

		extraction_facts = build_extraction_facts_from_facts(merged_facts)
		extraction_result = build_extraction_result_from_facts(extraction_facts)
		if extraction_result is not None:
			merged_metadata["source"] = extraction_result.source

		language = merged_metadata.get("language")
		return PromptContext(
			use_case_id=use_case_id,
			facts=merged_facts,
			extraction_facts=extraction_facts,
			extraction_result=extraction_result,
			text="\n\n".join(part for part in text_parts if part),
			image_base64=image_base64,
			language=str(language) if language is not None else None,
			metadata=merged_metadata,
		)

	def _needs_page_text(self, intent: ExtractionIntent) -> bool:
		"""Return True if any request needs text extraction from the page tree."""
		for request in intent.requests:
			if isinstance(request, PageTextRequest):
				return True
		return False

	def _resolve_shared_extraction_snapshot(self, intent: ExtractionIntent, kwargs: dict[str, Any]) -> ExtractionSnapshot | None:
		extraction_snapshot = kwargs.get("extraction_snapshot")
		if isinstance(extraction_snapshot, ExtractionSnapshot):
			return extraction_snapshot

		for collector in self._collectors:
			extractor = getattr(collector, "extractor", None)
			if extractor is None:
				continue
			try:
				snapshot = self._main_thread_executor(extractor.extract)
			except Exception:
				continue
			if isinstance(snapshot, ExtractionSnapshot):
				return snapshot
		return None
