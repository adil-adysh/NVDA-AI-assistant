# -*- coding: utf-8 -*-
from __future__ import annotations

from .types import UseCaseSpec


def build_default_use_case_specs() -> tuple[UseCaseSpec, ...]:
	return (
		UseCaseSpec(
			id="summary",
			description="Summarize the current page content.",
			context_profile=("app", "accessibility"),
			prompt_key="page_summary",
			tools=(),
			requires_input=False,
		),
		UseCaseSpec(
			id="describe_image",
			description="Describe the current foreground window screenshot.",
			context_profile=("image",),
			prompt_key="image_description",
			tools=(),
			requires_input=False,
		),
		UseCaseSpec(
			id="open_chat",
			description="Open a blank chat session.",
			context_profile=(),
			prompt_key="chat",
			tools=(),
			requires_input=False,
		),
		UseCaseSpec(
			id="open_chat_with_page_content",
			description="Open chat with the current page content preloaded.",
			context_profile=("app", "accessibility"),
			prompt_key="chat_with_page_context",
			tools=(),
			requires_input=True,
		),
		UseCaseSpec(
			id="open_chat_with_screenshot",
			description="Open chat with a screenshot attached.",
			context_profile=("image",),
			prompt_key="chat_with_image_context",
			tools=(),
			requires_input=True,
		),
	)
