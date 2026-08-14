# -*- coding: utf-8 -*-
"""Main-thread extraction of text from the focused editable control."""
from __future__ import annotations

from logHandler import log

from ..types import FocusedTextSnapshot


def extract_focused_text() -> FocusedTextSnapshot | None:
	"""Capture the complete focused edit-box value using NVDA's TextInfo API."""
	try:
		import api
		import textInfos
		from NVDAObjects.behaviors import EditableText

		focus = api.getFocusObject()
		if focus is None or not isinstance(focus, EditableText):
			return None

		info = focus.makeTextInfo(textInfos.POSITION_ALL)
		text = info.text
		if not isinstance(text, str) or not text.strip():
			return None

		app_module = getattr(focus, "appModule", None)
		app_title = getattr(app_module, "appName", None)
		return FocusedTextSnapshot(
			text=text,
			control_name=getattr(focus, "name", None),
			app_title=app_title if isinstance(app_title, str) else None,
			window_title=getattr(focus, "windowText", None),
		)
	except (RuntimeError, NotImplementedError):
		return None
	except Exception:
		log.exception("Error extracting focused edit-box text")
		return None
