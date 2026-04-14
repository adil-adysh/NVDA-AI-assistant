# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from .candidate_base import CandidateProvider, ExtractionContext


class GenericCandidateProvider(CandidateProvider):
	name = "generic"

	def supports(self, context: ExtractionContext) -> bool:
		return True

	def iterCandidates(self, context: ExtractionContext):
		for candidate in (context.focus, context.navigator, context.foreground):
			if candidate is not None:
				yield candidate

		focus = context.focus
		if focus is not None:
			root = getattr(focus, "treeInterceptor", None)
			if root is not None:
				yield root
				rootObj = getattr(root, "rootNVDAObject", None)
				if rootObj is not None:
					yield rootObj
