# -*- coding: utf-8 -*-
# Intentional structural mirror of the other result-producing use cases:
# spec/result building follow the same shape by design (R0801).
# pylint: disable=duplicate-code
from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

from ..context.pipeline import ContextPipeline
from ..context.navigation import build_llm_navigation_candidates
from ..prompts import build_extraction_structure_summary_prompt
from ..context.types import ExtractionIntent, PageStructureRequest, PromptContext
from ..service.llm import LLMService
from ..providers.interfaces import StructuredOutputNotSupportedError
from .base import UseCase, build_page_context_items
from .types import ResultOutputItem, UseCaseResult, UseCaseSpec
from .structure_summary_response import (
	STRUCTURE_SUMMARY_JSON_SCHEMA,
	parse_structure_summary_response,
	render_structure_summary,
)

class StructureSummaryUseCase(UseCase):
	@property
	def spec(self) -> UseCaseSpec:
		return UseCaseSpec(
			id="structure_summary",
			description="Summarize page structure, including headings, links, and interactive elements.",
			extraction_intent=ExtractionIntent(
				requests=(
					PageStructureRequest(),
				)
			),
			prompt_key="page_structure_summary",
			tools=(),
			requires_input=False,
			result_actions=True,
			# Structure fields are bounded by the prompt builder itself. The generic
			# reducer operates on page prose, which this prompt intentionally omits.
			context_policy="none",
			context_token_budget=4500,
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
			build_prompt=self._build_prompt,
			llm_call=lambda prompt, prompt_context, stream_handler: self._call_llm(
				llm_service, prompt, prompt_context, stream_handler
			),
			build_result=self._build_result,
			emit=emit,
			collecting_message="Collecting page content...",
			building_prompt_message="Building structure summary prompt...",
			llm_request_message="Generating structure summary...",
			context_reducer=kwargs.get("_context_reducer"),
			query=kwargs.get("query") if isinstance(kwargs.get("query"), str) else None,
		)

	def _build_result(self, prompt_context: PromptContext, response: object, prompt: str) -> UseCaseResult:
		extraction_result = self._get_extraction_result(prompt_context)
		candidates = build_llm_navigation_candidates(
			extraction_result.structure,
			graph=getattr(extraction_result, "graph", None),
		)
		validated = parse_structure_summary_response(response.text, candidates)
		output_text = render_structure_summary(validated, candidates)
		html_output = self.markdown_to_html(output_text)
		result_metadata = self._build_result_metadata(response, self.spec.prompt_key)
		target_by_id = {target.id: target for target in candidates}
		result_metadata["navigation_targets"] = [
			target_by_id[item.target_id].to_dict()
			for item in validated.destinations
			if item.target_id in target_by_id
		]
		result_metadata["structure_summary_structured"] = validated.structured
		return UseCaseResult(
			success=True,
			message="Structure summary ready",
			initial_text=None,
			output_text=output_text,
			output_html=html_output,
			is_browseable=True,
			prompt_context=PromptContext(
				use_case_id=self.spec.id,
				facts={"extraction_result": extraction_result},
				extraction_result=extraction_result,
				text=extraction_result.text,
				metadata=self._build_prompt_metadata(self.spec.prompt_key, prompt),
			),
			metadata=result_metadata,
			context_items=build_page_context_items(extraction_result, include_text=False),
			output_items=(ResultOutputItem(id="structure_summary", content=output_text),),
			navigation_context=getattr(extraction_result, "navigation_context", None),
		)

	@staticmethod
	def _call_llm(
		llm_service: LLMService,
		prompt: str,
		prompt_context: PromptContext,
		stream_handler: Callable[[str, int], None] | None,
	) -> object:
		"""Avoid a provider request when no accessible structure was collected."""
		extraction_result = prompt_context.extraction_result
		structure = getattr(extraction_result, "structure", None)
		graph = getattr(extraction_result, "graph", None)
		if not (
			any(
				getattr(structure, field, ())
				for field in (
					"headings", "links", "buttons", "landmarks", "inputs",
					"comboboxes", "checkboxes", "radios",
				)
			)
			or getattr(graph, "nodes", ())
		):
			return SimpleNamespace(
				text=(
					'{"overview":"No accessible page structure was detected.",'
					'"sections":[],"omissions":"The page exposed no usable headings, links, or controls."}'
				),
				provider="local",
				model="deterministic-fallback",
			)
		structured_call = getattr(llm_service, "summarize_structured", None)
		if callable(structured_call):
			try:
				return structured_call(
					prompt,
					schema=STRUCTURE_SUMMARY_JSON_SCHEMA,
					stream_handler=None,
				)
			except StructuredOutputNotSupportedError:
				pass
		return llm_service.summarize(prompt, stream_handler=stream_handler)

	def _build_prompt(self, prompt_context: PromptContext) -> str:
		extraction_result = self._get_extraction_result(prompt_context)
		input_token_budget = prompt_context.metadata.get("_prompt_input_token_limit")
		if not isinstance(input_token_budget, int):
			input_token_budget = None
		return build_extraction_structure_summary_prompt(
			extraction_result,
			language=prompt_context.language,
			input_token_budget=input_token_budget,
		)
