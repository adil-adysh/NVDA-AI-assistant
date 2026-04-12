# -*- coding: utf-8 -*-
from __future__ import annotations

from .types import ImageContext, PageContext


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
	headings = _format_headings(context.headings)
	links = _format_list(context.links)
	buttons = _format_list(context.buttons)
	landmarks = _format_list(context.landmarks)
	truncated_notice = "yes" if context.truncated else "no"

	return (
		f"{build_system_prompt_for_nvda_assistant()}\n"
		"Output EXACTLY:\n"
		"\n"
		"Overview:\n"
		"(1–2 sentences about page purpose)\n\n"
		"Key points:\n"
		"\n"
		"* (3 to 5 short points that matter to the user)\n\n"
		"Page structure summary:\n"
		"(Short description of layout/navigation)\n\n"
		"Actions (optional):\n"
		"\n"
		"* (Up to 3 useful next steps)\n\n"
		"Context:\n"
		f"App: {context.app_title or 'Unknown'}\n"
		f"Title: {context.title}\n"
		f"Trimmed: {truncated_notice}\n\n"
		"Counts:\n"
		f"Headings: {len(context.headings)}\n"
		f"Links: {len(context.links)}\n"
		f"Buttons: {len(context.buttons)}\n"
		f"Landmarks: {len(context.landmarks)}\n\n"
		"Headings:\n"
		f"{headings}\n\n"
		"Landmarks:\n"
		f"{landmarks}\n\n"
		"Links:\n"
		f"{links}\n\n"
		"Buttons:\n"
		f"{buttons}\n\n"
		"Content:\n"
		f"{context.text}"
	)


def build_image_description_prompt(context: ImageContext) -> str:
	"""Build a prompt for describing a captured foreground window image."""
	context_lines = []
	if context.app_title:
		context_lines.append(f"App: {context.app_title}")
	if context.window_title:
		context_lines.append(f"Window: {context.window_title}")

	context_section = "\n".join(context_lines) + "\n" if context_lines else ""

	return (
		f"{build_system_prompt_for_nvda_assistant()}\n"
		"Goal: Describe the visible window screenshot for someone using a screen reader.\n"
		"\n"
		"Rules:\n"
		"* Use ONLY the visible image contents. Do NOT guess or invent missing details.\n"
		"* Describe the layout, visible text, labels, buttons, controls, and any prominent sections.\n"
		"* Mention what is likely interactive, what appears disabled, and what is the main focus.\n"
		"* Include enough context so a blind user can understand the purpose of the screen and next steps.\n"
		"* If you cannot read a visual element clearly, say that it is uncertain or partially visible.\n"
		"* Do not repeat information or use vague language.\n"
		"\n"
		"Output EXACTLY:\n"
		"\n"
		"Overview:\n"
		"(1–2 sentences summarizing the visible window and its main purpose)\n\n"
		"Key points:\n"
		"\n"
		"* (3 to 5 short points describing important visible elements, text, and structure)\n\n"
		"Actions (optional):\n"
		"\n"
		"* (Up to 3 useful next steps or what the user can do next)\n\n"
		"Context:\n"
		f"{context_section}"
	)


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


def _format_headings(headings: tuple[tuple[int | None, str], ...]) -> str:
	if not headings:
		return "- None"
	return "\n".join(
		f"- H{level}: {text}" if level is not None else f"- {text}"
		for level, text in headings
	)


def _format_list(items: tuple[str, ...]) -> str:
	if not items:
		return "- None"
	return "\n".join(f"- {item}" for item in items)
