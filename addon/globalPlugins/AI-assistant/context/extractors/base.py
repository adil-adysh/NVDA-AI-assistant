# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from typing import Any

from logHandler import log

from ...context.protocols import NVDAContextProvider
from ...context.types import ContentSnapshot, SnapshotType
from .candidates import CandidateProvider, ExtractionContext, buildDefaultCandidateProviders

MAX_PAGE_TEXT_CHARS = 120000
MIN_PAGE_TEXT_CHARS = 120

_ELLIPSIS_BLOCK = "\n\n[Content trimmed before summarization]\n\n"


class PageExtractionError(RuntimeError):
	pass


class BasePageExtractor:
	def __init__(
		self,
		nvda_context_provider: NVDAContextProvider,
		candidateProviders: Sequence[CandidateProvider] | None = None,
	):
		super().__init__()
		log.debug(
			"BasePageExtractor initialized with %d candidate providers",
			len(candidateProviders or []),
		)
		self._nvda_context_provider = nvda_context_provider
		self._seenTextSignatures: set[str] = set()
		self._candidateProviders = tuple(candidateProviders or buildDefaultCandidateProviders())

	def extract(self) -> ContentSnapshot | None:
		raise NotImplementedError

	def _buildContext(self) -> ExtractionContext:
		focus = self._getFocusObjectSafe()
		focusTreeInterceptor = self._nvda_context_provider.get_tree_interceptor(focus)
		focusAncestors = self._getFocusAncestorsSafe()
		navigator = self._getNavigatorObjectSafe()
		foreground = self._getForegroundObjectSafe()

		log.debug(
			"BasePageExtractor._buildContext: focus=%s ancestors=%d navigator=%s foreground=%s",
			self._describeObject(focus),
			len(focusAncestors),
			self._describeObject(navigator),
			self._describeObject(foreground),
		)

		appName = self._nvda_context_provider.get_app_name(focus)
		if isinstance(appName, str) and appName.strip():
			appName = appName.strip().lower()
		elif foreground is not None:
			appName = self._nvda_context_provider.get_app_name(foreground)
			if isinstance(appName, str) and appName.strip():
				appName = appName.strip().lower()
		else:
			appName = None

		log.debug(
			"BasePageExtractor._buildContext: focus=%s ancestors=%d navigator=%s foreground=%s",
			self._describeObject(focus),
			len(focusAncestors),
			self._describeObject(navigator),
			self._describeObject(foreground),
		)

		appName = None
		appModule = getattr(focus, "appModule", None) if focus is not None else None
		maybeName = getattr(appModule, "appName", None) if appModule is not None else None
		if isinstance(maybeName, str) and maybeName.strip():
			appName = maybeName.strip().lower()
		elif foreground is not None:
			foregroundModule = getattr(foreground, "appModule", None)
			maybeName = getattr(foregroundModule, "appName", None) if foregroundModule is not None else None
			if isinstance(maybeName, str) and maybeName.strip():
				appName = maybeName.strip().lower()

		log.debug(
			"BasePageExtractor._buildContext: appName=%s focusTreeInterceptor=%s",
			appName,
			self._describeObject(focusTreeInterceptor),
		)

		return ExtractionContext(
			focus=focus,
			focusTreeInterceptor=focusTreeInterceptor,
			focusAncestors=focusAncestors,
			navigator=navigator,
			foreground=foreground,
			appName=appName,
		)

	def _getFocusObjectSafe(self) -> object | None:
		return self._nvda_context_provider.get_focus_object()

	def _getFocusAncestorsSafe(self) -> tuple[object, ...]:
		return self._nvda_context_provider.get_focus_ancestors()

	def _getNavigatorObjectSafe(self) -> object | None:
		return self._nvda_context_provider.get_navigator_object()

	def _getForegroundObjectSafe(self) -> object | None:
		return self._nvda_context_provider.get_foreground_object()

	def _buildSnapshot(
		self,
		obj: object,
		context: ExtractionContext,
		sourceName: str,
		trimmedText: str | None = None,
		truncated: bool | None = None,
	):
		if trimmedText is None or truncated is None:
			text = self._extractText(obj)
			normalized = self._normalizeText(text)
			log.debug(
				"BasePageExtractor: source=%s normalized text length=%d",
				sourceName,
				len(normalized),
			)
			if not self._isMeaningfulText(normalized):
				log.debug("BasePageExtractor: candidate rejected by text quality heuristic")
				return None

			trimmedText, truncated = self._trimText(normalized)
			textSignature = self._textSignature(trimmedText)
			if textSignature in self._seenTextSignatures:
				log.debug("BasePageExtractor: duplicate text content skipped")
				return None
			self._seenTextSignatures.add(textSignature)

		headings, links, buttons, landmarks = self._extractStructuredInfo(obj)

		return ContentSnapshot(
			snapshot_type=SnapshotType.GENERIC,
			title=self._extractTitle(obj, context),
			appTitle=self._extractAppTitle(context),
			text=trimmedText,
			truncated=truncated,
			headings=headings,
			links=links,
			buttons=buttons,
			landmarks=landmarks,
		)

	def _bestEffortSnapshot(
		self,
		obj: object,
		context: ExtractionContext,
		sourceName: str,
		browserInterceptor: object | None,
		currentBest: ContentSnapshot | None,
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

		headings, links, buttons, landmarks = self._extractStructuredInfo(obj)
		snapshot = ContentSnapshot(
			snapshot_type=SnapshotType.GENERIC,
			title=self._extractTitle(obj, context),
			appTitle=self._extractAppTitle(context),
			text=trimmedText,
			truncated=truncated,
			headings=headings,
			links=links,
			buttons=buttons,
			landmarks=landmarks,
		)
		score = self._candidateScore(obj, context, snapshot, sourceName, browserInterceptor)
		score += min(len(trimmedText), 500) // 25
		if score > currentScore:
			log.debug(
				"BasePageExtractor: selected best-effort source=%s score=%d",
				sourceName,
				score,
			)
			return snapshot, score
		return currentBest, currentScore

	def _candidateScore(
		self,
		obj: object,
		context: ExtractionContext,
		snapshot: ContentSnapshot,
		sourceName: str,
		browserInterceptor: object | None,
	) -> int:
		score = 0
		score += len(snapshot.headings) * 5
		score += min(len(snapshot.links), 40)
		score += len(snapshot.buttons) * 2
		score += len(snapshot.landmarks) * 6

		if sourceName == "browserTreeInterceptor":
			score += 30
		if self._looksLikeDocumentObject(obj):
			score += 20
		if self._sharesBrowserDocument(obj, browserInterceptor):
			score += 15
		if self._hasMainContentLandmark(snapshot):
			score += 40

		textLength = len(snapshot.text)
		if textLength >= 500:
			score += 10
		elif textLength >= MIN_PAGE_TEXT_CHARS:
			score += 5

		if len(snapshot.links) > 30 and len(snapshot.headings) <= 1 and textLength < 2000:
			score -= 20

		if context.focus is obj:
			score += 5

		return score

	def _shouldInspectCandidate(
		self,
		candidate: object,
		context: ExtractionContext,
		sourceName: str,
		browserInterceptor: object | None,
	) -> bool:
		return True

	def _sharesBrowserDocument(self, obj: object, browserInterceptor: object | None) -> bool:
		return False

	def _hasMainContentLandmark(self, snapshot: ContentSnapshot) -> bool:
		for landmark in snapshot.landmarks:
			normalized = landmark.strip().lower()
			if any(token in normalized for token in ("main", "content", "article", "feed")):
				return True
		return False

	def _looksLikeDocumentObject(self, obj: object) -> bool:
		roleText = str(getattr(obj, "role", "")).upper()
		typeName = type(obj).__name__.lower()
		return any(token in roleText for token in ("DOCUMENT", "ARTICLE", "INTERNALFRAME", "WEBVIEW")) or any(
			token in typeName for token in ("document", "web", "chromium")
		)

	def _extractText(self, obj: Any):
		for target in self._extractionTargets(obj):
			text = self._extractTextInfoText(target)
			if text:
				return text

		fragments: list[str] = []
		for attr in ("name", "value", "description", "displayText"):
			try:
				value = getattr(obj, attr, None)
			except Exception:
				value = None
			if isinstance(value, str) and value.strip():
				fragments.append(value.strip())
		return "\n".join(fragments)

	def _extractTextInfoText(self, obj: Any):
		textInfo = self._nvda_context_provider.make_text_info(obj)
		if textInfo is None:
			return None
		if textInfo is None:
			return None
		for method_name in ("getTextWithFields", "text"):
			try:
				value = getattr(textInfo, method_name, None)
			except Exception:
				value = None
			if callable(value):
				try:
					result = value()
					if isinstance(result, str) and result.strip():
						return result
				except Exception:
					pass
			elif isinstance(value, str) and value.strip():
				return value
		return None

	def _extractionTargets(self, obj: Any):
		yield obj
		for attr in ("rootNVDAObject", "parent", "next", "previous"):
			try:
				target = getattr(obj, attr, None)
			except Exception:
				target = None
			if target is not None:
				yield target

	def _extractStructuredInfo(self, obj: object):
		return (), (), (), ()

	def _extractTitle(self, obj: object, context: ExtractionContext) -> str:
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

	def _extractAppTitle(self, context: ExtractionContext) -> str:
		if context.appName:
			return context.appName
		return ""

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

	def _describeObject(self, obj: object | None) -> str:
		if obj is None:
			return "None"
		return f"{type(obj).__module__}.{type(obj).__name__}"

	def _describeSnapshot(self, snapshot: ContentSnapshot | None) -> str:
		if snapshot is None:
			return "None"
		return (
			f"ContentSnapshot(title={snapshot.title!r}, appTitle={snapshot.appTitle!r}, "
			f"text_len={len(snapshot.text)}, truncated={snapshot.truncated}, "
			f"headings={len(snapshot.headings)}, links={len(snapshot.links)}, "
			f"buttons={len(snapshot.buttons)}, landmarks={len(snapshot.landmarks)})"
		)
