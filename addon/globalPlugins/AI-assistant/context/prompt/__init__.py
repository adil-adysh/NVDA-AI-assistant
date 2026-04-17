# -*- coding: utf-8 -*-
from __future__ import annotations

from .registry import (
    get_prompt_template,
    register_user_prompt_override,
    render_prompt,
)
from .renderer import render_prompt_template
from .defaults import build_system_prompt_for_nvda_assistant
from ..types import ImageContext, PageContext, PromptContext


def build_page_summary_prompt(context: PageContext) -> str:
    prompt_context = PromptContext(
        use_case_id="summary",
        page_context=context,
        text=context.text,
        metadata={"prompt_key": "page_summary"},
    )
    return render_prompt("page_summary", prompt_context)


def build_image_description_prompt(context: ImageContext) -> str:
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
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    assistant_messages = assistant_messages or []
    for content in assistant_messages:
        messages.append({"role": "assistant", "content": content})

    for content in user_messages:
        messages.append({"role": "user", "content": content})

    return messages

__all__ = [
    "build_system_prompt_for_nvda_assistant",
    "build_page_summary_prompt",
    "build_image_description_prompt",
    "build_chat_messages",
    "get_prompt_template",
    "register_user_prompt_override",
    "render_prompt",
    "render_prompt_template",
]
