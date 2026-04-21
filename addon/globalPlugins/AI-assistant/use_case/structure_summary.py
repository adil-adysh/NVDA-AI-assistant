# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Callable

from ..context.pipeline import ContextPipeline
from ..prompts import build_extraction_structure_summary_prompt
from ..context.types import APP, PAGE, ExtractionResult, PromptContext
from ..service.llm import LLMService
from .base import UseCase
from .types import UseCaseResult, UseCaseSpec


class StructureSummaryUseCase(UseCase):
	@property
	def spec(self) -> UseCaseSpec:
		return UseCaseSpec(
			id="structure_summary",
			description="Summarize page structure, including headings, links, and interactive elements.",
			context_profile=(APP, PAGE),
			prompt_key="page_structure_summary",
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
			build_prompt=lambda prompt_context: build_extraction_structure_summary_prompt(self._get_extraction_result(prompt_context)),
			llm_call=lambda prompt, prompt_context: llm_service.summarize(prompt),
			build_result=self._build_result,
			emit=emit,
			collecting_message="Collecting page content...",
			building_prompt_message="Building structure summary prompt...",
			llm_request_message="Generating structure summary...",
		)

	def _get_extraction_result(self, prompt_context: PromptContext) -> ExtractionResult:
		extraction_result = prompt_context.extraction_result
		if extraction_result is None:
			raise ValueError("Unable to collect extraction result")
		return extraction_result

	def _build_result(self, prompt_context: PromptContext, response: object, prompt: str) -> UseCaseResult:
		extraction_result = self._get_extraction_result(prompt_context)
		html_output = self.markdown_to_html(response.text)
		return UseCaseResult(
			success=True,
			message="Structure summary ready",
			initial_text=extraction_result.text,
			prompt_context=PromptContext(
				use_case_id=self.spec.id,
				facts={"extraction_result": extraction_result},
				extraction_result=extraction_result,
				text=extraction_result.text,
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
