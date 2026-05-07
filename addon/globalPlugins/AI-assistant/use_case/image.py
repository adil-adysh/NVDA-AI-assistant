# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Callable

from ..context.pipeline import ContextPipeline
from ..prompts import build_image_description_prompt
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
		if not llm_service.supports_image_description():
			provider_name = llm_service.provider_name()
			raise ValueError(f"Image description is not supported by the active provider: {provider_name}")

		return self.execute_prompted_use_case(
			context_pipeline=context_pipeline,
			llm_service=llm_service,
			build_prompt=lambda prompt_context: build_image_description_prompt(
				self._get_image_context(prompt_context),
				language=prompt_context.language,
			),
			llm_call=lambda prompt, prompt_context, stream_handler: llm_service.describe_image(
				image_base64=self._get_image_context(prompt_context).image_base64 or "",
				prompt=prompt,
				stream_handler=stream_handler,
			),
			build_result=self._build_result,
			emit=emit,
			collecting_message="Collecting screenshot context...",
			building_prompt_message="Building image description prompt...",
			llm_request_message="Generating image description...",
		)

	def _get_image_context(self, prompt_context: PromptContext) -> ImageContext:
		image_context = prompt_context.facts.get("image_context")
		if not isinstance(image_context, ImageContext):
			raise ValueError("Unable to collect image context")
		return image_context

	def _build_result(self, prompt_context: PromptContext, response: object, prompt: str) -> UseCaseResult:
		image_context = self._get_image_context(prompt_context)
		html_output = self.markdown_to_html(response.text)
		# Ensure provider and model are included in metadata if present on response
		provider = getattr(response, "provider", None) or "unknown"
		model = getattr(response, "model", None) or "unknown"
		return UseCaseResult(
			success=True,
			message="Image description ready",
			initial_image_base64=image_context.image_base64,
			output_text=response.text,
			output_html=html_output,
			is_browseable=True,
			prompt_context=PromptContext(
				use_case_id=self.spec.id,
				facts={"image_context": image_context},
				image_base64=image_context.image_base64,
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
