# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Callable

from ..context.pipeline import ContextPipeline
from ..prompts import build_extraction_summary_prompt
from ..context.types import ExtractionIntent, ExtractionResult, PageStructureRequest, PageTextRequest, PromptContext
from ..service.llm import LLMService
from .base import UseCase
from .types import UseCaseResult, UseCaseSpec


class SummaryUseCase(UseCase):
	@property
	def spec(self) -> UseCaseSpec:
		return UseCaseSpec(
			id="summary",
			description="Summarize the current page content.",
			extraction_intent=ExtractionIntent(requests=(
				PageTextRequest(),
				PageStructureRequest(),
			)),
			prompt_key="page_summary",
			tools=(),
			requires_input=False,
			result_actions=True,
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
			build_prompt=lambda prompt_context: build_extraction_summary_prompt(
				self._get_extraction_result(prompt_context),
				language=prompt_context.language,
			),
			llm_call=lambda prompt, prompt_context, stream_handler: llm_service.summarize(prompt, stream_handler=stream_handler),
			build_result=self._build_result,
			emit=emit,
			collecting_message="Collecting page content...",
			building_prompt_message="Building summary prompt...",
			llm_request_message="Generating summary...",
		)

	def _get_extraction_result(self, prompt_context: PromptContext) -> ExtractionResult:
		extraction_result = prompt_context.extraction_result
		if extraction_result is None:
			raise ValueError("Unable to collect extraction result")
		return extraction_result

	def _build_result(self, prompt_context: PromptContext, response: object, prompt: str) -> UseCaseResult:
		extraction_result = self._get_extraction_result(prompt_context)
		html_output = self.markdown_to_html(response.text)
		provider = getattr(response, "provider", None) or "unknown"
		model = getattr(response, "model", None) or "unknown"
		return UseCaseResult(
			success=True,
			initial_text=extraction_result.text,
			output_text=response.text,
			output_html=html_output,
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
				"provider": provider,
				"model": model,
				"prompt_key": self.spec.prompt_key,
			},
		)
