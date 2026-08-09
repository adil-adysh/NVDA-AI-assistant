# -*- coding: utf-8 -*-
from __future__ import annotations

import dataclasses
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from ..context.formatting import format_page_context, format_page_structure
from ..context.pipeline import ContextPipeline
from ..context.types import ExtractionResult, PromptContext
from ..providers.interfaces import PartialCallback
from ..service.llm import LLMService
from ..utils.markdown import render_markdown_to_html
from .types import ResultContextItem, UseCaseResult, UseCaseSpec

logger = logging.getLogger(__name__)

ContextEmitter = Callable[[str, str], None] | None


def build_page_context_items(extraction_result: ExtractionResult) -> tuple[ResultContextItem, ...]:
	"""Build the context items a page-based use case exposes to the conversation.

	Only includes items that actually have usable data, so the presenter never
	offers actions for context that does not exist.
	"""
	items: list[ResultContextItem] = []
	page_content = format_page_context(
		extraction_result.title,
		extraction_result.app_title,
		extraction_result.text or "",
	)
	if page_content:
		items.append(ResultContextItem(id="page_content", content=page_content))
	structure_text = format_page_structure(extraction_result.structure)
	if structure_text:
		items.append(ResultContextItem(id="page_structure", content=structure_text))
	return tuple(items)


class UseCase(ABC):
	@property
	@abstractmethod
	def spec(self) -> UseCaseSpec:
		raise NotImplementedError

	@abstractmethod
	def execute(
		self,
		context_pipeline: ContextPipeline | None,
		llm_service: LLMService,
		emit: ContextEmitter = None,  # pylint: disable=unused-argument
		**kwargs: Any,
	) -> UseCaseResult:
		raise NotImplementedError

	def collect_prompt_context(
		self, context_pipeline: ContextPipeline | None, emit: ContextEmitter = None  # pylint: disable=unused-argument
	) -> PromptContext | None:
		if context_pipeline is None or not self.spec.extraction_intent.requests:
			return None
		return context_pipeline.collect(
			use_case_id=self.spec.id, extraction_intent=self.spec.extraction_intent
		)

	def _get_extraction_result(self, prompt_context: PromptContext) -> ExtractionResult:
		"""Return the extraction result carried by *prompt_context* or raise."""
		extraction_result = prompt_context.extraction_result
		if extraction_result is None:
			raise ValueError("Unable to collect extraction result")
		return extraction_result

	def _build_prompt_metadata(self, prompt_key: str, prompt: str) -> dict[str, int | str]:
		"""Metadata describing the prompt built for this use case."""
		return {"prompt_key": prompt_key, "prompt_chars": len(prompt)}

	def _build_result_metadata(self, response: object, prompt_key: str) -> dict[str, str]:
		"""Metadata describing the LLM response (provider/model provenance)."""
		provider = getattr(response, "provider", None) or "unknown"
		model = getattr(response, "model", None) or "unknown"
		return {"provider": provider, "model": model, "prompt_key": prompt_key}

	def execute_prompted_use_case(
		self,
		context_pipeline: ContextPipeline | None,
		llm_service: LLMService,  # pylint: disable=unused-argument
		build_prompt: Callable[[PromptContext], str],
		llm_call: Callable[[str, PromptContext, PartialCallback | None], Any],
		build_result: Callable[[PromptContext, Any, str], UseCaseResult],
		emit: ContextEmitter = None,
		collecting_message: str = "Collecting context...",
		building_prompt_message: str = "Building prompt...",
		llm_request_message: str = "Generating response...",
	) -> UseCaseResult:
		if emit is not None:
			emit("collecting_context", collecting_message)
		prompt_context = self.collect_prompt_context(context_pipeline, emit=emit)
		if prompt_context is None:
			raise ValueError("Unable to collect context")

		if emit is not None:
			emit("building_prompt", building_prompt_message)
		prompt = build_prompt(prompt_context)

		if emit is not None:
			emit("llm_request", llm_request_message)

		def stream_handler(partial_text: str, generated_chars: int) -> None:
			if emit is not None and generated_chars > 0:
				emit("streaming", partial_text)

		response = llm_call(prompt, prompt_context, stream_handler if emit is not None else None)

		response_text = getattr(response, "text", None)
		if response_text is not None:
			logger.debug("UseCase %s response.text=%s", self.spec.id, response_text)

		result = build_result(prompt_context, response, prompt)

		# Automatically propagate the spec's result_actions flag into result
		# metadata so the presenter never needs a hardcoded use-case-ID list.
		if self.spec.result_actions:
			meta = dict(result.metadata) if result.metadata else {}
			meta.setdefault("result_actions", True)
			result = dataclasses.replace(result, metadata=meta)

		return result

	def markdown_to_html(self, text: str) -> str:
		"""Convert markdown-style LLM output to HTML for browseable rendering."""
		return render_markdown_to_html(text)
