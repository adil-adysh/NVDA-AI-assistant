# -*- coding: utf-8 -*-
"""System clipboard utilities — pure Python, no external dependencies.

Uses NVDA's built-in ``api.getClipData()`` which internally drives the
``winUser.openClipboard`` context manager.  This is the canonical NVDA pattern
used throughout the NVDA source (``globalCommands.py``, ``MathCAT.py``).
"""

from __future__ import annotations

from logHandler import log


def safe_read_clipboard() -> str | None:
	"""Read text from the system clipboard.

	Returns the clipboard text string, or ``None`` if the clipboard is empty,
	contains non-text content, or cannot be read.
	"""
	try:
		import api

		return api.getClipData() or None
	except Exception:
		log.exception("Error reading clipboard via api.getClipData")
		return None
