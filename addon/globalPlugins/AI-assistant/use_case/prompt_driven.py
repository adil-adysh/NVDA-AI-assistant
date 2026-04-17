# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Callable

from logHandler import log
from ..context.prompt import render_prompt
from ..context.pipeline import ContextPipeline
from ..context.types import ImageContext, PromptContext
from ..core.message_transforms import build_user_message
from ..core.messages import LLMResponse, SummaryResponse
from ..service.llm import LLMService
from .base import UseCase
from .types import OutputFormat, UseCaseResult, UseCaseSpec

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
		log.info(
			"PromptDrivenUseCase start: %s prompt_template_key=%s llm_method=%s",
			self.spec.id,
			self.spec.prompt_template_key,
			self.spec.llm_method,
		)
		if emit is not None:
			emit("collecting_context", f"Collecting context for {self.spec.id}...")

		prompt_context = self.collect_prompt_context(context_pipeline, emit=emit)
		if prompt_context is None:
			prompt_context = PromptContext(use_case_id=self.spec.id, metadata={})
		elif self.spec.prompt_template_key is not None:
			prompt_context.metadata.setdefault("prompt_key", self.spec.prompt_template_key)

		if emit is not None:
			emit("building_prompt", f"Building {self.spec.id} prompt...")
		if self.spec.prompt_template is not None:
			prompt = self.spec.prompt_template
			prompt_source = "template"
		else:
			if self.spec.prompt_template_key is None:
				raise ValueError("PromptDrivenUseCase requires a prompt_template or prompt_template_key")
			prompt = render_prompt(self.spec.prompt_template_key, prompt_context)
			prompt_source = "key"
		log.debug("PromptDrivenUseCase rendered prompt for %s (source=%s chars=%d)", self.spec.id, prompt_source, len(prompt))

		response = self._dispatch_llm_method(llm_service, prompt_context, prompt, emit=emit)

		return UseCaseResult(
			success=True,
			message=f"{self.spec.description} complete",
			initial_text=prompt_context.text,
			initial_image_base64=prompt_context.image_base64,
			prompt_context=prompt_context,
			output_format="markdown" if self.spec.llm_method == "generate" else "text",
			metadata={
				"output_text": response.text,
				"model": response.model,
				"prompt_template_key": self.spec.prompt_template_key,
				"prompt_chars": len(prompt),
				"prompt_source": prompt_source,
			},
	)

	def _dispatch_llm_method(
		self,
		llm_service: LLMService,
		prompt_context: PromptContext,
		prompt: str,
		emit: ContextEmitter = None,
	) -> SummaryResponse | LLMResponse:
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

		if self.spec.llm_method == "generate":
			if emit is not None:
				emit("llm_request", "Generating text response...")
			message = build_user_message(text=prompt)
			return llm_service.generate(messages=[message])

		log.error("PromptDrivenUseCase unsupported llm_method for %s: %s", self.spec.id, self.spec.llm_method)
		raise ValueError(
			"PromptDrivenUseCase requires a valid llm_method: summarize, describe_image, or generate"
		)
