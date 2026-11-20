# -*- coding: utf-8 -*-
"""Declarative spelling and grammar correction use case."""
from __future__ import annotations

from dataclasses import replace

from ..core.thinking import extract_thinking_trace
from ..context.types import ExtractionIntent, FocusedElementTextRequest, FocusedTextSnapshot, PromptContext
from ..prompts import build_proofreading_prompt
from .declarative import DeclarativeUseCase, DeclarativeUseCaseDefinition
from .types import UseCaseResult


PROOFREAD_DEFINITION = DeclarativeUseCaseDefinition(
	id="proofread",
	description="Correct spelling and grammar in the focused edit box.",
	extraction_intent=ExtractionIntent(requests=(FocusedElementTextRequest(),)),
	prompt_key="proofreading",
	result_message="Spelling and grammar correction ready",
)


class ProofreadUseCase(DeclarativeUseCase):
	"""Run proofreading without exposing provider reasoning as corrected text."""

	def _build_result(self, prompt_context: PromptContext, response: object, prompt: str) -> UseCaseResult:
		trace = extract_thinking_trace(response)
		response_text = getattr(response, "text", None)
		if isinstance(response_text, str):
			snapshot = prompt_context.facts.get("focused_text_snapshot")
			source_text = snapshot.text if isinstance(snapshot, FocusedTextSnapshot) else ""
			cleaned = response_text
			if trace and trace in cleaned and trace not in source_text:
				cleaned = cleaned.replace(trace, "", 1)
			if "<think/>" not in source_text:
				cleaned = cleaned.replace("<think/>", "")
			if cleaned != response_text:
				response = replace(response, text=cleaned.strip())
		return super()._build_result(prompt_context, response, prompt)


def build_proofread_use_case() -> DeclarativeUseCase:
	def build_prompt(context: PromptContext) -> str:
		snapshot = context.facts.get("focused_text_snapshot")
		if not isinstance(snapshot, FocusedTextSnapshot):
			raise ValueError("Focused text snapshot is unavailable")
		return build_proofreading_prompt(snapshot, language=context.language)

	return ProofreadUseCase(PROOFREAD_DEFINITION, build_prompt)
