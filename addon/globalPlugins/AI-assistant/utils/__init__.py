# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .markdown import render_markdown_to_html

__all__ = ["render_markdown_to_html", "safe_read_clipboard"]

if TYPE_CHECKING:
	from .clipboard import safe_read_clipboard


def __getattr__(name: str) -> Any:
	"""Lazy export for clipboard utilities without eager loading at package import."""
	if name == "safe_read_clipboard":
		from .clipboard import safe_read_clipboard

		return safe_read_clipboard
	raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

