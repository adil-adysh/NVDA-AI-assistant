# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from ..context.collectors import ImageContextCollector, PageContextCollector
from ..context.pipeline import ContextPipeline
from ..core.events import ProgressEvent, ProgressHandler
from ..service import ChatCoordinator, LLMService
from .catalog import build_default_use_case_specs
from .chat import prepare_chat, prepare_chat_with_page_content, prepare_chat_with_screenshot
from .image import run_image_description_use_case
from .summary import run_summary_use_case
from .types import UseCaseResult, UseCaseSpec


class UseCaseEngine:
	def __init__(
		self,
		chat_coordinator: ChatCoordinator,
		llm_service: LLMService,
		context_pipeline: ContextPipeline | None = None,
		page_context_collector: PageContextCollector | None = None,
		image_context_collector: ImageContextCollector | None = None,
	) -> None:
		self._chat_coordinator = chat_coordinator
		self._llm_service = llm_service
		self._context_pipeline = context_pipeline
		self._page_context_collector = page_context_collector
		self._image_context_collector = image_context_collector
		self._specs = {spec.id: spec for spec in build_default_use_case_specs()}
		self._handlers = {
			"summary": self.summarize_current_page,
			"describe_image": self.describe_current_window,
			"open_chat": self.prepare_chat,
			"open_chat_with_page_content": self.prepare_chat_with_page_content,
			"open_chat_with_screenshot": self.prepare_chat_with_screenshot,
		}

	def get_spec(self, use_case_id: str) -> UseCaseSpec:
		try:
			return self._specs[use_case_id]
		except KeyError as error:
			raise ValueError(f"Unknown use case: {use_case_id}") from error

	def execute(self, use_case_id: str, progress: ProgressHandler | None = None, **kwargs: Any) -> UseCaseResult:
		def emit(stage: str, message: str) -> None:
			if progress is not None:
				progress(ProgressEvent(stage=stage, message=message))

		emit("start", f"Starting {use_case_id}")
		try:
			handler = self._handlers.get(use_case_id)
			if handler is None:
				raise ValueError(f"Unknown use case: {use_case_id}")
			result = handler(emit=emit, **kwargs)
		except Exception as error:
			emit("error", str(error))
			raise

		emit("complete", result.message or f"{use_case_id} complete")
		return result

	def summarize_current_page(self, emit: Any | None = None) -> UseCaseResult:
		return run_summary_use_case(
			llm_service=self._llm_service,
			page_context_collector=self._page_context_collector,
			emit=emit,
		)

	def describe_current_window(self, emit: Any | None = None) -> UseCaseResult:
		return run_image_description_use_case(
			llm_service=self._llm_service,
			image_context_collector=self._image_context_collector,
			emit=emit,
		)

	def prepare_chat(
		self,
		initial_text: str | None = None,
		initial_image_base64: str | None = None,
		emit: Any | None = None,
	) -> UseCaseResult:
		return prepare_chat(
			initial_text=initial_text,
			initial_image_base64=initial_image_base64,
			emit=emit,
		)

	def prepare_chat_with_page_content(self, page_content: str | None = None, emit: Any | None = None) -> UseCaseResult:
		return prepare_chat_with_page_content(
			context_pipeline=self._context_pipeline,
			page_content=page_content,
			emit=emit,
		)

	def prepare_chat_with_screenshot(self, initial_text: str | None = None, image_base64: str | None = None, emit: Any | None = None) -> UseCaseResult:
		return prepare_chat_with_screenshot(
			context_pipeline=self._context_pipeline,
			initial_text=initial_text,
			image_base64=image_base64,
			emit=emit,
		)
