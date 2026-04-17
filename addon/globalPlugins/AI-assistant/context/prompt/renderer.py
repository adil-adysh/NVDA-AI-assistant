# -*- coding: utf-8 -*-
from __future__ import annotations

import string
from typing import Any

from ..types import ImageContext, PageContext, PromptContext
from .defaults import build_system_prompt_for_nvda_assistant


def render_prompt_template(template: str, prompt_context: PromptContext) -> str:
    values = _build_render_values(prompt_context)
    try:
        return string.Template(template).safe_substitute(values)
    except Exception as error:
        raise ValueError(f"Unable to render prompt template: {error}") from error


def _build_render_values(prompt_context: PromptContext) -> dict[str, str]:
    page_context = prompt_context.page_context
    image_context = _find_image_context(prompt_context)

    return {
        "system_prompt": build_system_prompt_for_nvda_assistant(),
        "prompt_key": str(prompt_context.metadata.get("prompt_key", "")),
        "text": prompt_context.text or "",
        "page_title": page_context.title if page_context is not None else "",
        "app_title": page_context.app_title if page_context is not None else "",
        "page_text": page_context.text if page_context is not None else "",
        "truncated_notice": "yes" if page_context is not None and page_context.truncated else "no",
        "heading_count": str(len(page_context.headings) if page_context is not None else 0),
        "link_count": str(len(page_context.links) if page_context is not None else 0),
        "button_count": str(len(page_context.buttons) if page_context is not None else 0),
        "landmark_count": str(len(page_context.landmarks) if page_context is not None else 0),
        "headings": _format_headings(page_context.headings if page_context is not None else ()),
        "links": _format_list(page_context.links if page_context is not None else ()),
        "buttons": _format_list(page_context.buttons if page_context is not None else ()),
        "landmarks": _format_list(page_context.landmarks if page_context is not None else ()),
        "image_base64": prompt_context.image_base64 or "",
        "image_app_title": image_context.app_title or "",
        "image_window_title": image_context.window_title or "",
        "image_context": _format_image_context(image_context),
    }


def _find_image_context(prompt_context: PromptContext) -> ImageContext:
    image_context = prompt_context.facts.get("image_context")
    if isinstance(image_context, ImageContext):
        return image_context
    return ImageContext(
        app_title=None,
        window_title=None,
        image_base64=prompt_context.image_base64,
    )


def _format_image_context(context: ImageContext) -> str:
    lines: list[str] = []
    if context.app_title:
        lines.append(f"App: {context.app_title}")
    if context.window_title:
        lines.append(f"Window: {context.window_title}")
    if context.image_base64:
        lines.append("[IMAGE ATTACHED]")
    return "\n".join(lines) if lines else ""


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
