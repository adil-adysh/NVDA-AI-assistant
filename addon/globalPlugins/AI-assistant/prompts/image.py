# -*- coding: utf-8 -*-
from __future__ import annotations

from ..context.types import ImageContext
from .base import render_prompt_template


def build_image_description_prompt(context: ImageContext) -> str:
    """Build a prompt for describing a captured foreground window image."""
    return render_prompt_template(
        "image_description.jinja2",
        app_title=context.app_title,
        window_title=context.window_title,
    )
