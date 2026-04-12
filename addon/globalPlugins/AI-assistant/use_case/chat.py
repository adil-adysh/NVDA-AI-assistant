# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Callable

from ..context.pipeline import ContextPipeline
from ..context.types import PageContext, PromptContext
from .types import UseCaseResult


def prepare_chat(
	initial_text: str | None = None,
	initial_image_base64: str | None = None,
	emit: Callable[[str, str], None] | None = None,
) -> UseCaseResult:
	return UseCaseResult(
		success=True,
		initial_text=initial_text,
		initial_image_base64=initial_image_base64,
		message="Chat window ready",
		prompt_context=PromptContext(
			use_case_id="open_chat",
			facts={},
			text=initial_text,
			image_base64=initial_image_base64,
			metadata={"prompt_key": "chat"},
		),
	)


def prepare_chat_with_page_content(
	context_pipeline: ContextPipeline | None,
	page_content: str | None = None,
	emit: Callable[[str, str], None] | None = None,
) -> UseCaseResult:
	if emit is not None:
		emit("collecting_context", "Collecting page content...")
	prompt_context = _collect_prompt_context(context_pipeline, "open_chat_with_page_content")
	if emit is not None:
		emit("building_prompt", "Building chat prompt...")
	page_context = None
	if prompt_context is not None:
		page_context = prompt_context.facts.get("page_context")

	if isinstance(page_context, PageContext):
		title = page_context.title or "Unknown"
		app_title = page_context.app_title or "Unknown"
		page_content = (
			"Page content:\n"
			f"Title: {title}\n"
			f"App: {app_title}\n\n"
			f"{page_context.text}\n\n"
			"Question: "
		)
	elif not page_content and prompt_context is not None:
		page_content = prompt_context.text or ""

	return UseCaseResult(
		success=True,
		initial_text=page_content,
		message="Chat window ready",
		prompt_context=prompt_context,
		metadata={"prompt_key": "chat_with_page_context"},
	)


def prepare_chat_with_screenshot(
	context_pipeline: ContextPipeline | None,
	initial_text: str | None = None,
	image_base64: str | None = None,
	emit: Callable[[str, str], None] | None = None,
) -> UseCaseResult:
	if emit is not None:
		emit("collecting_context", "Collecting screenshot context...")
	prompt_context = _collect_prompt_context(context_pipeline, "open_chat_with_screenshot")
	if emit is not None:
		emit("building_prompt", "Building chat prompt...")
	if prompt_context is not None:
		image_base64 = prompt_context.image_base64 or image_base64
		if not initial_text:
			initial_text = "Describe this screenshot."

	return UseCaseResult(
		success=True,
		initial_text=initial_text,
		initial_image_base64=image_base64,
		message="Chat window ready",
		prompt_context=prompt_context,
		metadata={"prompt_key": "chat_with_image_context"},
	)


def _collect_prompt_context(context_pipeline: ContextPipeline | None, use_case_id: str) -> PromptContext | None:
	if context_pipeline is None:
		return None
	if use_case_id == "open_chat_with_page_content":
		context_profile = ("app", "accessibility")
	else:
		context_profile = ("image",)
	return context_pipeline.collect(use_case_id=use_case_id, context_profile=context_profile)
