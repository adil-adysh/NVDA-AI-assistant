# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Callable

from ..context.pipeline import ContextPipeline
from ..context.types import ExtractionIntent, ImageContext, PromptContext
from ..image import capture_focused_object
from ..image.services import ImageEncoder, ImagePreprocessor
from ..prompts import build_image_description_prompt
from ..service.llm import LLMService
from .base import UseCase
from .types import UseCaseResult, UseCaseSpec


class DescribeFocusedImageUseCase(UseCase):
	"""Capture the currently focused NVDA object and describe it using the LLM."""

	@property
	def spec(self) -> UseCaseSpec:
		return UseCaseSpec(
			id="describe_focused_image",
			description="Describe the currently focused NVDA object image.",
			extraction_intent=ExtractionIntent(),
			prompt_key="image_description",
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
		if not llm_service.supports_image_description():
			provider_name = llm_service.provider_name()
			raise ValueError(f"Image description is not supported by the active provider: {provider_name}")

		if emit is not None:
			emit("collecting_context", "Capturing focused object image...")

		try:
			capture = capture_focused_object(
				preprocessor=ImagePreprocessor(),
				encoder=ImageEncoder(),
				main_thread_executor=(
					context_pipeline.run_on_main_thread if context_pipeline is not None else None
				),
			)
		except RuntimeError as e:
			return UseCaseResult(
				success=False,
				error_message=str(e),
				message="Failed to capture focused object",
			)

		image_context = ImageContext(
			app_title=capture.app_name,
			window_title=capture.window_title,
			image_base64=capture.image_base64,
		)

		if emit is not None:
			emit("building_prompt", "Building image description prompt...")

		prompt = build_image_description_prompt(
			image_context,
			language=None,
		)

		if emit is not None:
			emit("llm_request", "Generating image description...")

		def stream_handler(partial_text: str, generated_chars: int) -> None:
			if emit is not None and generated_chars > 0:
				emit("streaming", partial_text)

		response = llm_service.describe_image(
			image_base64=capture.image_base64,
			prompt=prompt,
			stream_handler=stream_handler if emit is not None else None,
		)

		html_output = self.markdown_to_html(response.text)

		return UseCaseResult(
			success=True,
			message="Focused image description ready",
			initial_image_base64=capture.image_base64,
			output_text=response.text,
			output_html=html_output,
			is_browseable=True,
			prompt_context=PromptContext(
				use_case_id=self.spec.id,
				facts={
					"focus_capture": {
						"object_name": capture.object_name,
						"object_role": capture.object_role,
						"app_name": capture.app_name,
						"window_title": capture.window_title,
						"left": capture.left,
						"top": capture.top,
						"width": capture.width,
						"height": capture.height,
					},
				},
				image_base64=capture.image_base64,
				metadata=self._build_prompt_metadata(self.spec.prompt_key, prompt),
			),
			metadata=self._build_result_metadata(response, self.spec.prompt_key),
		)


class AttachFocusedImageToChatUseCase(UseCase):
	"""Capture the currently focused NVDA object and attach it to a new chat session."""

	@property
	def spec(self) -> UseCaseSpec:
		return UseCaseSpec(
			id="attach_focused_image_to_chat",
			description="Open chat with the focused NVDA object image attached.",
			extraction_intent=ExtractionIntent(),
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
			emit("collecting_context", "Capturing focused object image...")

		try:
			capture = capture_focused_object(
				preprocessor=ImagePreprocessor(),
				encoder=ImageEncoder(),
				main_thread_executor=(
					context_pipeline.run_on_main_thread if context_pipeline is not None else None
				),
			)
		except RuntimeError as e:
			return UseCaseResult(
				success=False,
				error_message=str(e),
				message="Failed to capture focused object",
			)

		if emit is not None:
			emit("building_prompt", "Building chat prompt...")

		# Build an initial descriptive text from focus metadata
		parts: list[str] = []
		if capture.object_role:
			parts.append(f"Focused element role: {capture.object_role}")
		if capture.object_name:
			parts.append(f"Name: {capture.object_name}")
		if capture.app_name:
			parts.append(f"Application: {capture.app_name}")
		if capture.window_title:
			parts.append(f"Window: {capture.window_title}")

		initial_text = "\n".join(parts) if parts else None

		provider = "unknown"
		model = "unknown"
		return UseCaseResult(
			success=True,
			initial_text=initial_text,
			initial_image_base64=capture.image_base64,
			message="Chat window ready with focused object image",
			prompt_context=PromptContext(
				use_case_id=self.spec.id,
				facts={
					"focus_capture": {
						"object_name": capture.object_name,
						"object_role": capture.object_role,
						"app_name": capture.app_name,
						"window_title": capture.window_title,
					},
				},
				image_base64=capture.image_base64,
				metadata={"prompt_key": self.spec.prompt_key},
			),
			metadata={
				"provider": provider,
				"model": model,
				"prompt_key": self.spec.prompt_key,
			},
		)
