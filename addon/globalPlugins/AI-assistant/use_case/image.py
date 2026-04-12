# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Callable

from ..context.collectors import ImageContextCollector
from ..context.prompts import build_image_description_prompt
from ..context.types import ImageContext, PromptContext
from ..service.llm import LLMService
from ..observability.metrics import estimate_tokens
from .types import UseCaseResult


def run_image_description_use_case(
	llm_service: LLMService,
	image_context_collector: ImageContextCollector | None,
	emit: Callable[[str, str], None] | None = None,
) -> UseCaseResult:
	if emit is not None:
		emit("collecting_context", "Collecting screenshot context...")
	image_context = _collect_image_context(image_context_collector)
	if emit is not None:
		emit("building_prompt", "Building image description prompt...")
	prompt = build_image_description_prompt(image_context)
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
			use_case_id="describe_image",
			facts={"image_context": image_context},
			image_base64=image_context.image_base64,
			metadata={
				"prompt_key": "image_description",
				"prompt_chars": len(prompt),
				"prompt_tokens_estimated": estimate_tokens(prompt),
			},
		),
		metadata={"output_text": response.text, "model": response.model, "prompt_key": "image_description"},
	)


def _collect_image_context(image_context_collector: ImageContextCollector | None) -> ImageContext:
	if image_context_collector is not None:
		fragment = image_context_collector.collect("describe_image")
		image_context = fragment.facts.get("image_context")
		if isinstance(image_context, ImageContext):
			return image_context
	raise ValueError("Unable to collect image context")
