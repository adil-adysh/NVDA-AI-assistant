# -*- coding: utf-8 -*-
from __future__ import annotations

from .prompt import render_prompt
from .types import ImageContext, PageContext, PromptContext


def build_system_prompt_for_nvda_assistant() -> str:
	"""Build the shared system prompt for the NVDA assistant."""
	return (
		"Role: NVDA accessibility assistant.\n"
		"\n"
		"Goal: Give a quick, useful understanding of the task or content.\n"
		"\n"
		"Rules:\n"
		"* Use ONLY given content. Do NOT guess.\n"
		"* Be concise and practical.\n"
		"* Do not repeat information.\n"
		"\n"
		"Process:\n"
		"1. Read the instructions carefully.\n"
		"2. Use the available content to answer clearly.\n"
		"3. Keep language simple and direct.\n"
	)


def build_page_summary_prompt(context: PageContext) -> str:
	"""Build a page summary prompt from structured page context."""
	prompt_context = PromptContext(
		use_case_id="summary",
		page_context=context,
		text=context.text,
		metadata={"prompt_key": "page_summary"},
	)
	return render_prompt("page_summary", prompt_context)

def build_image_description_prompt(context: ImageContext) -> str:
	"""Build a prompt for describing a captured foreground window image."""
	prompt_context = PromptContext(
		use_case_id="describe_image",
		facts={"image_context": context},
		image_base64=context.image_base64,
		metadata={"prompt_key": "image_description"},
	)
	return render_prompt("image_description", prompt_context)


def build_chat_messages(
		 system_prompt: str,
		 user_messages: list[str],
		 assistant_messages: list[str] | None = None,
	) -> list[dict[str, str]]:
	"""Build a structured message list for interactive chat."""
	messages: list[dict[str, str]] = []
	if system_prompt:
		messages.append({"role": "system", "content": system_prompt})

	assistant_messages = assistant_messages or []
	for content in assistant_messages:
		messages.append({"role": "assistant", "content": content})

	for content in user_messages:
		messages.append({"role": "user", "content": content})

	return messages
