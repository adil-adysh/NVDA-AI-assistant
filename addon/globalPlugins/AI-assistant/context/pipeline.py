# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Callable, Sequence, TypeVar

from .protocols import CollectorInput, ContextCollector
from .types import (
	ContextCollectionError,
	ContextFacts,
	ExtractionIntent,
	ExtractionSnapshot,
	FocusedElementImageRequest,
	ForegroundImageRequest,
	ImageCaptureSnapshot,
	ImageCaptureSource,
	NavigatorImageRequest,
	PageTextRequest,
	PromptContext,
	PromptMetadata,
	build_extraction_result_from_facts,
	build_extraction_facts_from_facts,
)

T = TypeVar("T")
MainThreadExecutor = Callable[[Callable[..., T]], T]

# Map image request types to capture sources.
_IMAGE_SOURCES: dict[type, ImageCaptureSource] = {
	ForegroundImageRequest: "foreground",
	FocusedElementImageRequest: "focus",
	NavigatorImageRequest: "navigator",
}


class ContextPipeline:
	def __init__(self, collectors: Sequence[ContextCollector], main_thread_executor: MainThreadExecutor) -> None:
		self._collectors = tuple(collectors)
		self._main_thread_executor = main_thread_executor

	def collect(self, use_case_id: str, extraction_intent: ExtractionIntent, **kwargs: Any) -> PromptContext:
		if not extraction_intent.requests:
			return PromptContext(use_case_id=use_case_id, metadata={})

		# ── Phase 1: resolve shared snapshots on the NVDA main thread ──
		text_snapshot = self._resolve_text_snapshot(extraction_intent)
		image_snapshots = self._resolve_image_snapshots(extraction_intent)

		# ── Phase 2: dispatch requests to collectors (thread-safe) ──
		collector_input = CollectorInput(
			use_case_id=use_case_id,
			extraction_snapshot=text_snapshot,
			image_snapshots=image_snapshots,
		)
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

	# ── Snapshot resolution (NVDA main thread) ─────────────────────

	def _needs_text_snapshot(self, intent: ExtractionIntent) -> bool:
		for request in intent.requests:
			if isinstance(request, PageTextRequest):
				return True
		return False

	def _image_requests(self, intent: ExtractionIntent) -> list[type]:
		"""Return distinct image request types present in the intent."""
		seen: set[type] = set()
		result: list[type] = []
		for request in intent.requests:
			t = type(request)
			if t in _IMAGE_SOURCES and t not in seen:
				seen.add(t)
				result.append(t)
		return result

	def _resolve_text_snapshot(self, intent: ExtractionIntent) -> ExtractionSnapshot | None:
		if not self._needs_text_snapshot(intent):
			return None
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
		raise ContextCollectionError("Unable to obtain page snapshot for requested text extraction")

	def _resolve_image_snapshots(self, intent: ExtractionIntent) -> dict[ImageCaptureSource, ImageCaptureSnapshot]:
		"""Capture images on the main thread for all image request types."""
		result: dict[ImageCaptureSource, ImageCaptureSnapshot] = {}
		request_types = self._image_requests(intent)
		if not request_types:
			return result

		# Import lazily so the image package is not loaded on context import.
		from ..image.services import ImageCaptureService
		from ..image.screen_curtain import check_screen_curtain

		def _capture_all() -> list[ImageCaptureSnapshot]:
			check_screen_curtain()
			capture_service = ImageCaptureService()
			snapshots: list[ImageCaptureSnapshot] = []
			for req_type in request_types:
				source = _IMAGE_SOURCES[req_type]
				try:
					raw_bytes = capture_service.capture(source=source)
				except Exception:
					continue
				snapshots.append(ImageCaptureSnapshot(
					raw_bytes=raw_bytes,
					source=source,
				))
			return snapshots

		try:
			snapshots = self._main_thread_executor(_capture_all)
		except Exception:
			return result

		for snap in snapshots:
			result[snap.source] = snap
		return result
