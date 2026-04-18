# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Callable

from ..context.pipeline import ContextPipeline
from ..context.prompts import build_page_summary_prompt
from ..context.types import APP, PAGE, PageContext, PromptContext
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
		return self.execute_prompted_use_case(
			context_pipeline=context_pipeline,
			llm_service=llm_service,
			build_prompt=lambda prompt_context: build_page_summary_prompt(self._get_page_context(prompt_context)),
			llm_call=lambda prompt, prompt_context: llm_service.summarize(prompt),
			build_result=self._build_result,
			emit=emit,
			collecting_message="Collecting page content...",
			building_prompt_message="Building summary prompt...",
			llm_request_message="Generating summary...",
		)

	def _get_page_context(self, prompt_context: PromptContext) -> PageContext:
		page_context = prompt_context.page_context
		if page_context is None:
			raise ValueError("Unable to collect page context")
		return page_context

	def _build_result(self, prompt_context: PromptContext, response: object, prompt: str) -> UseCaseResult:
		page_context = self._get_page_context(prompt_context)
		html_output = self.markdown_to_html(response.text)
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
			metadata={
				"output_text": html_output,
				"is_html": True,
				"model": response.model,
				"prompt_key": self.spec.prompt_key,
			},
		)
