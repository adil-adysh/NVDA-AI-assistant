# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from .candidate_base import CandidateProvider, ExtractionContext


class TextEditorCandidateProvider(CandidateProvider):
	name = "textEditor"
	_TEXT_EDITOR_APP_NAMES = {
		"code",
		"notepad",
		"notepad++",
		"devenv",
	}

	def supports(self, context: ExtractionContext) -> bool:
		return context.appName in self._TEXT_EDITOR_APP_NAMES

	def iterCandidates(self, context: ExtractionContext) -> Any:
		if context.focus is not None:
			yield context.focus
			parent = getattr(context.focus, "parent", None)
			if parent is not None:
				yield parent

		if context.navigator is not None:
			yield context.navigator

		if context.foreground is not None:
			yield context.foreground
