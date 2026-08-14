# -*- coding: utf-8 -*-
"""Declarative use-case support for extension authors."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..context.pipeline import ContextPipeline
from ..context.types import ExtractionIntent, PromptContext
from ..service.llm import LLMService
from .base import UseCase
from .types import ResultOutputItem, UseCaseResult, UseCaseSpec


PromptBuilder = Callable[[PromptContext], str]


@dataclass(frozen=True, slots=True)
class DeclarativeUseCaseDefinition:
	"""Configuration for a standard prompt-and-response use case."""

	id: str
	description: str
	extraction_intent: ExtractionIntent
	prompt_key: str
	result_message: str
	llm_operation: str = "summarize"
	context_policy: str = "none"
	context_token_budget: int | None = None
	context_window_tokens: int | None = None
	reserved_output_tokens: int = 1024
	budget_safety_margin_tokens: int = 256
	result_actions: bool = False
	output_item_id: str | None = None


class DeclarativeUseCase(UseCase):
	"""Generic runner for use cases that collect context, build a prompt, and call one LLM operation."""

	def __init__(self, definition: DeclarativeUseCaseDefinition, prompt_builder: PromptBuilder) -> None:
		self.definition = definition
		self._prompt_builder = prompt_builder

	@property
	def spec(self) -> UseCaseSpec:
		return UseCaseSpec(
			id=self.definition.id,
			description=self.definition.description,
			extraction_intent=self.definition.extraction_intent,
			prompt_key=self.definition.prompt_key,
			requires_input=False,
			result_actions=self.definition.result_actions,
			context_policy=self.definition.context_policy,
			context_token_budget=self.definition.context_token_budget,
			context_window_tokens=self.definition.context_window_tokens,
			reserved_output_tokens=self.definition.reserved_output_tokens,
			budget_safety_margin_tokens=self.definition.budget_safety_margin_tokens,
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
			build_prompt=self._prompt_builder,
			llm_call=self._build_llm_call(llm_service),
			build_result=self._build_result,
			emit=emit,
			collecting_message="Collecting context...",
			building_prompt_message="Building prompt...",
			llm_request_message="Generating response...",
			context_reducer=kwargs.get("_context_reducer"),
			query=kwargs.get("query") if isinstance(kwargs.get("query"), str) else None,
		)

	def _build_llm_call(self, llm_service: LLMService):
		if self.definition.llm_operation == "summarize":
			return lambda prompt, _context, stream_handler: llm_service.summarize(
				prompt, stream_handler=stream_handler
			)
		raise ValueError(f"Unknown declarative LLM operation: {self.definition.llm_operation}")

	def _build_result(self, prompt_context: PromptContext, response: object, prompt: str) -> UseCaseResult:
		output_item_id = self.definition.output_item_id or self.definition.id
		return UseCaseResult(
			success=True,
			message=self.definition.result_message,
			initial_text=prompt_context.text,
			output_text=response.text,
			output_html=self.markdown_to_html(response.text),
			is_browseable=True,
			prompt_context=prompt_context,
			metadata=self._build_result_metadata(response, self.definition.prompt_key),
			output_items=(ResultOutputItem(id=output_item_id, content=response.text),),
		)
