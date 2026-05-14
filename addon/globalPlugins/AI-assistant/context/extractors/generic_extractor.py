# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Sequence

from logHandler import log

from .base import TreeExtractor
from .candidate_base import CandidateProvider, CandidateExtractionContext
from .candidates import buildGenericCandidateProviders
from .extraction_utils import (
	MIN_PAGE_TEXT_CHARS,
	extract_app_title,
	extract_text_from_object,
	extract_title,
	is_meaningful_text,
	normalize_extracted_text,
	text_signature,
	trim_text,
)
from .text_extractor import TextExtractor
from ...context.types import ExtractionSnapshot, GENERIC, TERMINAL, PromptSource


class GenericPageExtractor(TreeExtractor):
	def __init__(self, candidate_providers: Sequence[CandidateProvider] | None = None):
		self._seenTextSignatures: set[str] = set()
		self._candidateProviders = tuple(candidate_providers or buildGenericCandidateProviders())
		self._text_extractor = TextExtractor()

	def supports(self, context: CandidateExtractionContext) -> bool:
		return any(provider.supports(context) for provider in self._candidateProviders)

	def extract(self, context: CandidateExtractionContext):
		self._seenTextSignatures.clear()
		active_providers = [provider for provider in self._candidateProviders if provider.supports(context)]
		best_snapshot = None
		best_score = -1
		best_effort_snapshot = None
		best_effort_score = -1

		for provider in active_providers:
			log.debug("GenericPageExtractor.extract: iterating provider=%s", provider.name)
			seen_candidates: set[int] = set()
			for candidate in provider.iterCandidates(context):
				identity = id(candidate)
				if candidate is None or identity in seen_candidates:
					continue
				seen_candidates.add(identity)
				log.debug("GenericPageExtractor.extract: provider=%s candidate=%s", provider.name, type(candidate).__name__)

				text = self._extractText(candidate)
				normalized = self._normalizeText(text)
				if not self._isMeaningfulText(normalized):
					best_effort_snapshot, best_effort_score = self._bestEffortSnapshot(
						candidate,
						context,
						sourceName=provider.name,
						currentBest=best_effort_snapshot,
						currentScore=best_effort_score,
						normalizedText=normalized,
					)
					continue

				trimmed_text, truncated = self._trimText(normalized)
				text_signature = self._textSignature(trimmed_text)
				if text_signature in self._seenTextSignatures:
					continue
				self._seenTextSignatures.add(text_signature)

				snapshot = self._buildSnapshot(candidate, context, sourceName=provider.name, trimmedText=trimmed_text, truncated=truncated)
				if snapshot is not None:
					score = self._candidateScore(candidate, context, snapshot, provider.name, None)
					if score > best_score:
						best_snapshot = snapshot
						best_score = score

		if best_snapshot is not None:
			return best_snapshot
		if best_effort_snapshot is not None:
			return best_effort_snapshot
		return None

	def _extractText(self, obj: object) -> str:
		return extract_text_from_object(obj, self._text_extractor)

	def _normalizeText(self, text: str) -> str:
		return normalize_extracted_text(text)

	def _isMeaningfulText(self, text: str) -> bool:
		return is_meaningful_text(text)

	def _trimText(self, text: str) -> tuple[str, bool]:
		return trim_text(text)

	def _textSignature(self, text: str) -> str:
		return text_signature(text)

	def _buildSnapshot(
		self,
		obj: object,
		context: CandidateExtractionContext,
		sourceName: str,
		trimmedText: str,
		truncated: bool,
	):
		return ExtractionSnapshot(
			source=self._prompt_source(sourceName),
			title=self._extractTitle(obj, context),
			appTitle=self._extractAppTitle(context),
			text=trimmedText,
			truncated=truncated,
		)

	def _bestEffortSnapshot(
		self,
		obj: object,
		context: CandidateExtractionContext,
		sourceName: str,
		currentBest: ExtractionSnapshot | None,
		currentScore: int,
		normalizedText: str | None = None,
	):
		if normalizedText is None:
			normalizedText = self._normalizeText(self._extractText(obj))
		if not normalizedText:
			return currentBest, currentScore
		trimmedText, truncated = self._trimText(normalizedText)
		textSignature = self._textSignature(trimmedText)
		if textSignature in self._seenTextSignatures:
			return currentBest, currentScore
		snapshot = ExtractionSnapshot(
			source=self._prompt_source(sourceName),
			title=self._extractTitle(obj, context),
			appTitle=self._extractAppTitle(context),
			text=trimmedText,
			truncated=truncated,
		)
		score = self._candidateScore(obj, context, snapshot, sourceName, None)
		if score > currentScore:
			return snapshot, score
		return currentBest, currentScore

	def _prompt_source(self, sourceName: str) -> PromptSource:
		return TERMINAL if sourceName == "terminal" else GENERIC

	def _candidateScore(
		self,
		obj: object,
		context: CandidateExtractionContext,
		snapshot: ExtractionSnapshot,
		sourceName: str,
		browserInterceptor: object | None,
	) -> int:
		score = 0
		textLength = len(snapshot.text)
		if textLength >= 500:
			score += 10
		elif textLength >= MIN_PAGE_TEXT_CHARS:
			score += 5
		if context.focus is obj:
			score += 5
		return score

	def _extractTitle(self, obj: object, context: CandidateExtractionContext) -> str:
		return extract_title(obj, context)

	def _extractAppTitle(self, context: CandidateExtractionContext) -> str:
		return extract_app_title(context)
