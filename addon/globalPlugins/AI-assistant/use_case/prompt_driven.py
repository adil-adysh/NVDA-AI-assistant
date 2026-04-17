# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Callable

from ..context.prompt import render_prompt
from ..context.pipeline import ContextPipeline
from ..context.types import ImageContext, PromptContext
from ..core.messages import SummaryResponse
from ..service.llm import LLMService
from .base import UseCase
from .types import UseCaseResult, UseCaseSpec

ContextEmitter = Callable[[str, str], None] | None


class PromptDrivenUseCase(UseCase):
	def __init__(self, spec: UseCaseSpec | None = None) -> None:
		self._spec = spec

	@property
	def spec(self) -> UseCaseSpec:
		if self._spec is None:
			raise NotImplementedError("PromptDrivenUseCase requires a UseCaseSpec")
		return self._spec

	def execute(
		self,
		context_pipeline: ContextPipeline | None,
		llm_service: LLMService,
		emit: ContextEmitter = None,
		**kwargs: object,
	) -> UseCaseResult:
		if emit is not None:
			emit("collecting_context", f"Collecting context for {self.spec.id}...")

		prompt_context = self.collect_prompt_context(context_pipeline, emit=emit)
		if prompt_context is None:
			prompt_context = PromptContext(use_case_id=self.spec.id, metadata={})
		else:
			prompt_context.metadata.setdefault("prompt_key", self.spec.prompt_key)

		if emit is not None:
			emit("building_prompt", f"Building {self.spec.id} prompt...")
		prompt = render_prompt(self.spec.prompt_key, prompt_context)

		response = self._dispatch_llm_method(llm_service, prompt_context, prompt, emit=emit)

		return UseCaseResult(
			success=True,
			message=f"{self.spec.description} complete",
			initial_text=prompt_context.text,
			initial_image_base64=prompt_context.image_base64,
			prompt_context=prompt_context,
			metadata={
				"output_text": response.text,
				"model": response.model,
				"prompt_key": self.spec.prompt_key,
				"prompt_chars": len(prompt),
			},
		)

	def _dispatch_llm_method(
		self,
		llm_service: LLMService,
		prompt_context: PromptContext,
		prompt: str,
		emit: ContextEmitter = None,
	) -> SummaryResponse:
		if self.spec.llm_method == "summarize":
			if emit is not None:
				emit("llm_request", "Generating summary...")
			return llm_service.summarize(prompt)

		if self.spec.llm_method == "describe_image":
			if emit is not None:
				emit("llm_request", "Generating image description...")
			image_context = prompt_context.facts.get("image_context")
			image_base64 = None
			if isinstance(image_context, ImageContext):
				image_base64 = image_context.image_base64
			if not image_base64:
				image_base64 = prompt_context.image_base64 or ""
			return llm_service.describe_image(image_base64=image_base64, prompt=prompt)

		raise ValueError(
			"PromptDrivenUseCase requires a valid llm_method: summarize or describe_image"
		)
