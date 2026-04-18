# -*- coding: utf-8 -*-
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from ..context.pipeline import ContextPipeline
from ..context.types import PromptContext
from ..service.llm import LLMService
from ..utils.markdown import render_markdown_to_html
from .types import UseCaseResult, UseCaseSpec

ContextEmitter = Callable[[str, str], None] | None


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
		emit: ContextEmitter = None,
		**kwargs: Any,
	) -> UseCaseResult:
		raise NotImplementedError

	def collect_prompt_context(self, context_pipeline: ContextPipeline | None, emit: ContextEmitter = None) -> PromptContext | None:
		if context_pipeline is None or not self.spec.context_profile:
			return None
		if emit is not None:
			emit("collecting_context", f"Collecting context for {self.spec.id}...")
		return context_pipeline.collect(use_case_id=self.spec.id, context_profile=self.spec.context_profile)

	def execute_prompted_use_case(
		self,
		context_pipeline: ContextPipeline | None,
		llm_service: LLMService,
		build_prompt: Callable[[PromptContext], str],
		llm_call: Callable[[str, PromptContext], Any],
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
		response = llm_call(prompt, prompt_context)

		return build_result(prompt_context, response, prompt)

	def markdown_to_html(self, text: str) -> str:
		"""Convert markdown-style LLM output to HTML for browseable rendering."""
		return render_markdown_to_html(text)
