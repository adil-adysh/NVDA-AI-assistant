# -*- coding: utf-8 -*-
from __future__ import annotations

from html import escape as html_escape

from .mathml import convert_math_delimiters_to_mathml


def render_markdown_to_html(text: str) -> str:
    """Convert markdown text to HTML using the shared extension set."""
    if not isinstance(text, str) or not text:
        return ""

    try:
        import markdown
    except ImportError:
        return html_escape(text)

    text = convert_math_delimiters_to_mathml(text)

    base_extensions = [
        "extra",
        "sane_lists",
        "smarty",
        "toc",
        "nl2br",
        "admonition",
    ]
    codehilite_extensions = base_extensions + ["codehilite"]
    codehilite_config = {
        "codehilite": {
            "noclasses": True,
            "guess_lang": False,
        },
    }

    try:
        return markdown.markdown(
            text,
            extensions=codehilite_extensions,
            extension_configs=codehilite_config,
            output_format="html",
        )
    except Exception:
        try:
            return markdown.markdown(
                text,
                extensions=base_extensions,
                output_format="html",
            )
        except Exception:
            return html_escape(text)
