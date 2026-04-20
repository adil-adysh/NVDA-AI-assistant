# -*- coding: utf-8 -*-
from __future__ import annotations

from .base import (
    build_chat_messages,
    build_system_prompt_for_nvda_assistant,
)
from .image import build_image_description_prompt
from .summary import (
    build_browser_summary_prompt,
    build_extraction_summary_prompt,
    build_generic_summary_prompt,
    build_summary_prompt,
    build_terminal_summary_prompt,
)

__all__ = [
    "build_chat_messages",
    "build_system_prompt_for_nvda_assistant",
    "build_image_description_prompt",
    "build_summary_prompt",
    "build_extraction_summary_prompt",
    "build_browser_summary_prompt",
    "build_terminal_summary_prompt",
    "build_generic_summary_prompt",
]
