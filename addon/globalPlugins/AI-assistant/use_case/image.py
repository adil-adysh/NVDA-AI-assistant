# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Callable

from ..context.pipeline import ContextPipeline
from ..context.prompt import render_prompt
from ..context.types import IMAGE, ImageContext, PromptContext
from ..service.llm import LLMService
from .base import UseCase
from .types import UseCaseResult, UseCaseSpec


class ImageDescriptionUseCase(UseCase):
	@property
	def spec(self) -> UseCaseSpec:
		return UseCaseSpec(
			id="describe_image",
			description="Describe the current foreground window screenshot.",
			context_profile=(IMAGE,),
			prompt_key="image_description",
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
			emit("collecting_context", "Collecting screenshot context...")
		prompt_context = self.collect_prompt_context(context_pipeline, emit=emit)
		if prompt_context is None:
			raise ValueError("Unable to collect image context")
		image_context = prompt_context.facts.get("image_context")
		if not isinstance(image_context, ImageContext):
			raise ValueError("Unable to collect image context")

		if emit is not None:
			emit("building_prompt", "Building image description prompt...")
		prompt = render_prompt(self.spec.prompt_key, prompt_context)
		if emit is not None:
			emit("llm_request", "Generating image description...")
		response = llm_service.describe_image(
			image_base64=image_context.image_base64 or "",
			prompt=prompt,
		)

		return UseCaseResult(
			success=True,
			message="Image description ready",
			initial_image_base64=image_context.image_base64,
			prompt_context=PromptContext(
				use_case_id=self.spec.id,
				facts={"image_context": image_context},
				image_base64=image_context.image_base64,
				metadata={
					"prompt_key": self.spec.prompt_key,
					"prompt_chars": len(prompt),
				},
			),
			metadata={"output_text": response.text, "model": response.model, "prompt_key": self.spec.prompt_key},
		)
