# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Callable

from ..context.pipeline import ContextPipeline
from ..context.types import ExtractionIntent, ForegroundImageRequest, PageTextRequest, PromptContext
from ..service.llm import LLMService
from .base import UseCase
from .types import UseCaseResult, UseCaseSpec


class OpenChatUseCase(UseCase):
	@property
	def spec(self) -> UseCaseSpec:
		return UseCaseSpec(
			id="open_chat",
			description="Open a blank chat session.",
			extraction_intent=ExtractionIntent(),
			prompt_key="chat",
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
		provider = "unknown"
		model = "unknown"
		return UseCaseResult(
			success=True,
			initial_text=kwargs.get("initial_text"),
			initial_image_base64=kwargs.get("initial_image_base64"),
			message="Chat window ready",
			prompt_context=PromptContext(
				use_case_id=self.spec.id,
				facts={},
				text=kwargs.get("initial_text"),
				image_base64=kwargs.get("initial_image_base64"),
				metadata={"prompt_key": self.spec.prompt_key},
			),
			metadata={
				"provider": provider,
				"model": model,
				"prompt_key": self.spec.prompt_key,
			},
		)


class OpenChatWithPageContentUseCase(UseCase):
	@property
	def spec(self) -> UseCaseSpec:
		return UseCaseSpec(
			id="open_chat_with_page_content",
			description="Open chat with the current page content preloaded.",
			extraction_intent=ExtractionIntent(requests=(
				PageTextRequest(),
			)),
			prompt_key="chat_with_page_context",
			tools=(),
			requires_input=True,
		)

	def execute(
		self,
		context_pipeline: ContextPipeline | None,
		llm_service: LLMService,
		emit: Callable[[str, str], None] | None = None,
		**kwargs: object,
	) -> UseCaseResult:
		if emit is not None:
			emit("collecting_context", "Collecting page content...")
		prompt_context = self.collect_prompt_context(context_pipeline, emit=emit)
		if emit is not None:
			emit("building_prompt", "Building chat prompt...")

		page_content = kwargs.get("page_content")
		if prompt_context is not None:
			extraction_result = prompt_context.extraction_result
			if extraction_result is not None:
				title = extraction_result.title or "Unknown"
				app_title = extraction_result.app_title or "Unknown"
				page_content = (
					"Page content:\n"
					f"Title: {title}\n"
					f"App: {app_title}\n\n"
					f"{extraction_result.text}\n\n"
					"Question: "
				)
			elif page_content is None:
				page_content = prompt_context.text or ""

		provider = getattr(prompt_context, "provider", None) or "unknown"
		model = getattr(prompt_context, "model", None) or "unknown"
		return UseCaseResult(
			success=True,
			initial_text=page_content,
			message="Chat window ready",
			prompt_context=prompt_context,
			metadata={
				"provider": provider,
				"model": model,
				"prompt_key": self.spec.prompt_key,
			},
		)


class OpenChatWithScreenshotUseCase(UseCase):
	@property
	def spec(self) -> UseCaseSpec:
		return UseCaseSpec(
			id="open_chat_with_screenshot",
			description="Open chat with a screenshot attached.",
			extraction_intent=ExtractionIntent(requests=(
				ForegroundImageRequest(),
			)),
			prompt_key="chat_with_image_context",
			tools=(),
			requires_input=True,
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
		if emit is not None:
			emit("building_prompt", "Building chat prompt...")

		initial_text = kwargs.get("initial_text")
		image_base64 = kwargs.get("image_base64")
		if prompt_context is not None:
			image_base64 = prompt_context.image_base64 or image_base64
			if not initial_text:
				initial_text = "Describe this screenshot."

		provider = getattr(prompt_context, "provider", None) or "unknown"
		model = getattr(prompt_context, "model", None) or "unknown"
		return UseCaseResult(
			success=True,
			initial_text=initial_text,
			initial_image_base64=image_base64,
			message="Chat window ready",
			prompt_context=prompt_context,
			metadata={
				"provider": provider,
				"model": model,
				"prompt_key": self.spec.prompt_key,
			},
		)
