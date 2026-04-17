# -*- coding: utf-8 -*-
from __future__ import annotations

from __future__ import annotations

from .registry import (
    get_prompt_template,
    prompt_template_exists,
    register_user_prompt_override,
    render_prompt,
)
from .renderer import render_prompt_template
from .defaults import (
    build_system_prompt_for_nvda_assistant,
    CHAT_KEY,
    CHAT_WITH_IMAGE_CONTEXT_KEY,
    CHAT_WITH_PAGE_CONTEXT_KEY,
    IMAGE_DESCRIPTION_KEY,
    PAGE_SUMMARY_KEY,
)

__all__ = [
    "build_system_prompt_for_nvda_assistant",
    "get_prompt_template",
    "prompt_template_exists",
    "register_user_prompt_override",
    "render_prompt",
    "render_prompt_template",
    "CHAT_KEY",
    "CHAT_WITH_PAGE_CONTEXT_KEY",
    "CHAT_WITH_IMAGE_CONTEXT_KEY",
    "IMAGE_DESCRIPTION_KEY",
    "PAGE_SUMMARY_KEY",
]
