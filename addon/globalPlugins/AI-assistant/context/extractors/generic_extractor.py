# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from typing import Any

from logHandler import log

from .base import TreeExtractor
from .text_extractor import TextExtractor
from .candidate_base import CandidateProvider, CandidateExtractionContext
from .candidates import buildGenericCandidateProviders
from ...context.types import ExtractionSnapshot

MAX_PAGE_TEXT_CHARS = 120000
MIN_PAGE_TEXT_CHARS = 120
_ELLIPSIS_BLOCK = "\n\n[Content trimmed before summarization]\n\n"


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
		return self._text_extractor.extract_text(obj) or ""

	def _normalizeText(self, text: str) -> str:
		text = re.sub(r"[ \t]+", " ", text)
		text = re.sub(r"\n{3,}", "\n\n", text)
		return text.strip()

	def _isMeaningfulText(self, text: str) -> bool:
		return len(text.strip()) >= MIN_PAGE_TEXT_CHARS

	def _trimText(self, text: str) -> tuple[str, bool]:
		if len(text) <= MAX_PAGE_TEXT_CHARS:
			return text, False
		return text[:MAX_PAGE_TEXT_CHARS] + _ELLIPSIS_BLOCK, True

	def _textSignature(self, text: str) -> str:
		return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()

	def _buildSnapshot(
		self,
		obj: object,
		context: CandidateExtractionContext,
		sourceName: str,
		trimmedText: str,
		truncated: bool,
	):
		return ExtractionSnapshot(
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
			title=self._extractTitle(obj, context),
			appTitle=self._extractAppTitle(context),
			text=trimmedText,
			truncated=truncated,
		)
		score = self._candidateScore(obj, context, snapshot, sourceName, None)
		if score > currentScore:
			return snapshot, score
		return currentBest, currentScore

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
		for attr in ("name", "title", "description"):
			try:
				value = getattr(obj, attr, None)
			except Exception:
				value = None
			if isinstance(value, str) and value.strip():
				return value.strip()
		if context.foreground is not None:
			for attr in ("name", "title", "description"):
				try:
					value = getattr(context.foreground, attr, None)
				except Exception:
					value = None
				if isinstance(value, str) and value.strip():
					return value.strip()
		return ""

	def _extractAppTitle(self, context: CandidateExtractionContext) -> str:
		if context.appName:
			return context.appName
		return ""
