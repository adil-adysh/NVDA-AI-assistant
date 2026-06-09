# -*- coding: utf-8 -*-
"""Extract user-highlighted (selected) text from the focused NVDA object.

Follows NVDA's canonical pattern from ``globalCommands.GlobalCommands._getSelection``:
try the tree interceptor first (browser virtual buffer), then fall back to the
focus object itself.  Catches only ``RuntimeError`` and ``NotImplementedError``
— the exceptions NVDA's ``TextInfo`` raises when there is no selection.
"""

from __future__ import annotations

from logHandler import log


def safe_extract_selection() -> str | None:
	"""Extract user-highlighted text from the currently focused NVDA object.

	Returns the selected text string, or ``None`` if there is no selection
	or the extraction fails.

	Must be called on the NVDA main thread (gesture handler).
	"""
	try:
		import api
		from textInfos import POSITION_SELECTION

		focus = api.getFocusObject()
		if focus is None:
			return None

		# Try the focus object's tree interceptor first (browser-like apps)
		tree_interceptor = getattr(focus, "treeInterceptor", None)
		if (
			isinstance(tree_interceptor, object)
			and hasattr(tree_interceptor, "makeTextInfo")
		):
			try:
				info = tree_interceptor.makeTextInfo(POSITION_SELECTION)
				text = info.text
				if isinstance(text, str) and text.strip():
					return text.strip()
			except (RuntimeError, NotImplementedError):
				pass

		# Fall back to the focus object itself
		if hasattr(focus, "makeTextInfo"):
			try:
				info = focus.makeTextInfo(POSITION_SELECTION)
				text = info.text
				if isinstance(text, str) and text.strip():
					return text.strip()
			except (RuntimeError, NotImplementedError):
				pass

		return None
	except Exception:
		log.exception("Error extracting selection from focus")
		return None
