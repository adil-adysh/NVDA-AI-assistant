# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportImplicitOverride=false
from __future__ import annotations

from typing import Any

from .browser_candidates import BrowserCandidateProvider
from .candidate_base import CandidateProvider, CandidateExtractionContext
from .generic_candidates import GenericCandidateProvider
from .terminal_candidates import TerminalCandidateProvider
from .text_editor_candidates import TextEditorCandidateProvider


def buildDefaultCandidateProviders() -> tuple[CandidateProvider, ...]:
	return (
		BrowserCandidateProvider(),
		TextEditorCandidateProvider(),
		TerminalCandidateProvider(),
		GenericCandidateProvider(),
	)


def buildGenericCandidateProviders() -> tuple[CandidateProvider, ...]:
	return (
		TextEditorCandidateProvider(),
		TerminalCandidateProvider(),
		GenericCandidateProvider(),
	)


class TextAppCandidateProvider(CandidateProvider):
	name = "textApp"

	def __init__(self) -> None:
		self._providers = (
			TextEditorCandidateProvider(),
			TerminalCandidateProvider(),
		)

	def supports(self, context: CandidateExtractionContext) -> bool:
		return any(provider.supports(context) for provider in self._providers)

	def iterCandidates(self, context: CandidateExtractionContext):
		seen: set[int] = set()
		for provider in self._providers:
			for candidate in provider.iterCandidates(context):
				identity = id(candidate)
				if candidate is None or identity in seen:
					continue
				seen.add(identity)
				yield candidate
