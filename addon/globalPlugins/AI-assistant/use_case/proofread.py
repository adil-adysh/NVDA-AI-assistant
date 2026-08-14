# -*- coding: utf-8 -*-
"""Declarative spelling and grammar correction use case."""
from __future__ import annotations

from ..context.types import ExtractionIntent, FocusedElementTextRequest, FocusedTextSnapshot, PromptContext
from ..prompts import build_proofreading_prompt
from .declarative import DeclarativeUseCase, DeclarativeUseCaseDefinition


PROOFREAD_DEFINITION = DeclarativeUseCaseDefinition(
	id="proofread",
	description="Correct spelling and grammar in the focused edit box.",
	extraction_intent=ExtractionIntent(requests=(FocusedElementTextRequest(),)),
	prompt_key="proofreading",
	result_message="Spelling and grammar correction ready",
)


def build_proofread_use_case() -> DeclarativeUseCase:
	def build_prompt(context: PromptContext) -> str:
		snapshot = context.facts.get("focused_text_snapshot")
		if not isinstance(snapshot, FocusedTextSnapshot):
			raise ValueError("Focused text snapshot is unavailable")
		return build_proofreading_prompt(snapshot, language=context.language)

	return DeclarativeUseCase(PROOFREAD_DEFINITION, build_prompt)
