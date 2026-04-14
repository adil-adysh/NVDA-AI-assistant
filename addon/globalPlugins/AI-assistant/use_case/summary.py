# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Callable

from ..context.collectors import PageContextCollector
from ..context.prompts import build_page_summary_prompt
from ..context.types import PageContext, PromptContext
from ..service.llm import LLMService
from ..observability.metrics import estimate_tokens
from ..ui import nvda_ui
from .types import UseCaseResult


def run_summary_use_case(
	llm_service: LLMService,
	page_context_collector: PageContextCollector | None,
	emit: Callable[[str, str], None] | None = None,
) -> UseCaseResult:
	if emit is not None:
		emit("collecting_context", "Collecting page content...")
	page_context = _collect_page_context(page_context_collector)
	if emit is not None:
		emit("building_prompt", "Building summary prompt...")
	prompt = build_page_summary_prompt(page_context)
	if emit is not None:
		emit("llm_request", "Generating summary...")
	response = llm_service.summarize(prompt)
	return UseCaseResult(
		success=True,
		message="Summary ready",
		initial_text=page_context.text,
		prompt_context=PromptContext(
			use_case_id="summary",
			facts={"page_context": page_context},
			text=page_context.text,
			metadata={
				"prompt_key": "page_summary",
				"prompt_chars": len(prompt),
				"prompt_tokens_estimated": estimate_tokens(prompt),
			},
		),
		metadata={"output_text": response.text, "model": response.model, "prompt_key": "page_summary"},
	)


def _collect_page_context(page_context_collector: PageContextCollector | None) -> PageContext:
	if page_context_collector is not None:
		fragment = nvda_ui.call(page_context_collector.collect, "summary")
		page_context = fragment.facts.get("page_context")
		if isinstance(page_context, PageContext):
			return page_context
	raise ValueError("Unable to collect page context")
