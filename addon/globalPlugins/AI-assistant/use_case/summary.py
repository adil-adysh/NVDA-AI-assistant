# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Callable

from ..context.pipeline import ContextPipeline
from ..context.prompt import render_prompt
from ..context.types import APP, PAGE, PromptContext
from ..service.llm import LLMService
from .base import UseCase
from .types import UseCaseResult, UseCaseSpec


class SummaryUseCase(UseCase):
	@property
	def spec(self) -> UseCaseSpec:
		return UseCaseSpec(
			id="summary",
			description="Summarize the current page content.",
			context_profile=(APP, PAGE),
			prompt_key="page_summary",
			tools=(),
			requires_input=False,
		)

	def execute(
		self,
		context_pipeline: ContextPipeline | None,
		llm_service: LLMService,
		emit: Callable[[str, str], None] | None = None,
		**kwargs: object,
	) -> UseCaseResult:
		if emit is not None:
			emit("collecting_context", "Collecting page content...")
		prompt_context = self.collect_prompt_context(context_pipeline, emit=emit)
		if prompt_context is None:
			raise ValueError("Unable to collect page context")
		page_context = prompt_context.page_context
		if page_context is None:
			raise ValueError("Unable to collect page context")

		if emit is not None:
			emit("building_prompt", "Building summary prompt...")
		if emit is not None:
			emit("llm_request", "Generating summary...")
		prompt = render_prompt(self.spec.prompt_key, prompt_context)
		response = llm_service.summarize(prompt)

		return UseCaseResult(
			success=True,
			message="Summary ready",
			initial_text=page_context.text,
			prompt_context=PromptContext(
				use_case_id=self.spec.id,
				facts={"page_context": page_context},
				page_context=page_context,
				text=page_context.text,
				metadata={
					"prompt_key": self.spec.prompt_key,
					"prompt_chars": len(prompt),
				},
			),
			metadata={"output_text": response.text, "model": response.model, "prompt_key": self.spec.prompt_key},
		)
