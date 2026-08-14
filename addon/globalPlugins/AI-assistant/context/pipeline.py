# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Callable, Sequence, TypeVar

from .protocols import CollectorInput, ContextCollector
from .request_registry import ContextRequestRegistry
from .types import (
	ContextCollectionError,
	ContextFacts,
	ExtractionIntent,
	ExtractionSnapshot,
	FocusedTextSnapshot,
	ImageCaptureSnapshot,
	ImageCaptureSource,
	PromptContext,
	PromptMetadata,
	request_kind,
	build_extraction_result_from_facts,
	build_extraction_facts_from_facts,
)

T = TypeVar("T")
MainThreadExecutor = Callable[[Callable[..., T]], T]

class ContextPipeline:
	def __init__(
		self,
		collectors: Sequence[ContextCollector],
		main_thread_executor: MainThreadExecutor,
		page_extractor: Callable[..., ExtractionSnapshot | None] | None = None,
		focused_text_extractor: Callable[..., FocusedTextSnapshot | None] | None = None,
		request_registry: ContextRequestRegistry | None = None,
	) -> None:
		self._collectors = tuple(collectors)
		self._main_thread_executor = main_thread_executor
		self._page_extractor = page_extractor
		self._focused_text_extractor = focused_text_extractor
		self._request_registry = request_registry or ContextRequestRegistry()

	def collect(self, use_case_id: str, extraction_intent: ExtractionIntent) -> PromptContext:
		if not extraction_intent.requests:
			return PromptContext(use_case_id=use_case_id, metadata={})
		self._request_registry.validate(tuple(request_kind(request) for request in extraction_intent.requests))

		# ── Phase 1: resolve shared snapshots on the NVDA main thread ──
		text_snapshot = self._resolve_page_snapshot(extraction_intent)
		focused_text_snapshot = self._resolve_focused_text_snapshot(extraction_intent)
		image_snapshots = self._resolve_image_snapshots(extraction_intent)

		# ── Phase 2: dispatch requests to collectors (thread-safe) ──
		collector_input = CollectorInput(
			use_case_id=use_case_id,
			extraction_snapshot=text_snapshot,
			image_snapshots=image_snapshots,
			focused_text_snapshot=focused_text_snapshot,
		)
		merged_facts: ContextFacts = {}
		merged_metadata: PromptMetadata = {}
		text_parts: list[str] = []
		image_base64: str | None = None

		for request in extraction_intent.requests:
			matching_collectors: list[ContextCollector] = []
			has_request_collector = False
			for collector in self._collectors:
				handler = getattr(collector, "handles_request", None)
				if handler is None or not handler(request):
					continue
				matching_collectors.append(collector)
				if not getattr(collector, "always_collect", False):
					has_request_collector = True
			if not has_request_collector:
				raise ContextCollectionError(
					f"No context collector registered for request {type(request).__name__}"
				)
			for collector in matching_collectors:
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

	def run_on_main_thread(self, callable_: Callable[[], T]) -> T:
		"""Execute *callable_* on the NVDA main thread and return its result.

		Uses the same main-thread executor as snapshot resolution (the official
		``queueHandler.queueFunction(queueHandler.eventQueue, ...)`` pattern via
		``nvda_ui.call``), so background-thread code can safely touch NVDA's
		thread-affine object model.
		"""
		return self._main_thread_executor(callable_)

	# ── Snapshot resolution (NVDA main thread) ─────────────────────

	def _needs_page_snapshot(self, intent: ExtractionIntent) -> bool:
		for request in intent.requests:
			if self._request_registry.get(request_kind(request)).resolver == "page":
				return True
		return False

	def _needs_focused_text_snapshot(self, intent: ExtractionIntent) -> bool:
		return any(
			self._request_registry.get(request_kind(request)).resolver == "focused_text"
			for request in intent.requests
		)

	def _image_requests(self, intent: ExtractionIntent) -> list[ImageCaptureSource]:
		"""Return distinct image request types present in the intent."""
		seen: set[ImageCaptureSource] = set()
		result: list[ImageCaptureSource] = []
		for request in intent.requests:
			definition = self._request_registry.get(request_kind(request))
			if definition.image_source and definition.image_source not in seen:
				seen.add(definition.image_source)
				result.append(definition.image_source)
		return result

	def _resolve_page_snapshot(self, intent: ExtractionIntent) -> ExtractionSnapshot | None:
		if not self._needs_page_snapshot(intent):
			return None
		if self._page_extractor is None:
			raise ContextCollectionError(
				"A page extractor is required for page text or structure requests"
			)
		try:
			snapshot = self._main_thread_executor(self._page_extractor)
		except Exception as error:
			raise ContextCollectionError("Unable to obtain page snapshot") from error
		if not isinstance(snapshot, ExtractionSnapshot):
			raise ContextCollectionError("Page extractor returned no usable snapshot")
		return snapshot

	def _resolve_focused_text_snapshot(
		self, intent: ExtractionIntent
	) -> FocusedTextSnapshot | None:
		if not self._needs_focused_text_snapshot(intent):
			return None
		if self._focused_text_extractor is None:
			raise ContextCollectionError(
				"A focused text extractor is required for focused text requests"
			)
		try:
			snapshot = self._main_thread_executor(self._focused_text_extractor)
		except Exception as error:
			raise ContextCollectionError("Unable to obtain focused edit-box text") from error
		if not isinstance(snapshot, FocusedTextSnapshot):
			raise ContextCollectionError("Focused control is not an editable text field")
		if not snapshot.text.strip():
			raise ContextCollectionError("The focused edit box contains no text")
		return snapshot

	def _resolve_image_snapshots(
		self, intent: ExtractionIntent
	) -> dict[ImageCaptureSource, ImageCaptureSnapshot]:
		"""Capture images on the main thread for all image request types."""
		result: dict[ImageCaptureSource, ImageCaptureSnapshot] = {}
		request_types = self._image_requests(intent)
		if not request_types:
			return result

		# Import lazily so the image package is not loaded on context import.
		from ..image.services import ImageCaptureService
		from ..image.screen_curtain import ScreenCurtainError, check_screen_curtain

		def _capture_all() -> list[ImageCaptureSnapshot]:
			check_screen_curtain()
			capture_service = ImageCaptureService()
			snapshots: list[ImageCaptureSnapshot] = []
			for req_type in request_types:
				source = req_type
				try:
					raw_bytes = capture_service.capture(source=source)
				except ScreenCurtainError:
					# User-actionable; must not be masked as an internal error.
					raise
				except Exception:
					continue
				snapshots.append(
					ImageCaptureSnapshot(
						raw_bytes=raw_bytes,
						source=source,
					)
				)
			return snapshots

		try:
			snapshots = self._main_thread_executor(_capture_all)
		except ScreenCurtainError:
			raise
		except Exception:
			return result

		for snap in snapshots:
			result[snap.source] = snap
		return result
