# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Sequence

from logHandler import log

try:
	import treeInterceptorHandler
except Exception:  # pragma: no cover
	treeInterceptorHandler = None

from ...context.types import BrowserExtractionSnapshot
from .base import TreeExtractor
from .browser_candidates import BrowserCandidateProvider
from .candidate_base import is_usable_tree_interceptor
from .browser_field_parser import BrowserFieldParser
from .browser_target_resolver import BrowserTargetResolver
from .text_extractor import TextExtractor
from .candidates import CandidateProvider, CandidateExtractionContext
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


class PageExtractionError(RuntimeError):
	pass


class BrowserAwarePageExtractor(TreeExtractor):
	_BROWSER_APP_NAMES = {
		"chrome",
		"msedge",
		"firefox",
		"brave",
		"opera",
		"vivaldi",
	}

	def __init__(
		self,
		candidateProviders: Sequence[CandidateProvider] | None = None,
	):
		log.debug(
			"BrowserAwarePageExtractor initialized with %d candidate providers",
			len(candidateProviders or []),
		)
		self._seenTextSignatures: set[str] = set()
		self._candidateProviders = tuple(candidateProviders or (BrowserCandidateProvider(),))
		self._target_resolver = BrowserTargetResolver()
		self._text_extractor = TextExtractor()
		self._field_parser = BrowserFieldParser()

	def supports(self, context: CandidateExtractionContext) -> bool:
		if not self._isBrowserContext(context):
			return False
		browser_target = self._target_resolver.resolve(context)
		return browser_target is not None

	def extract(self, context: CandidateExtractionContext):
		log.debug("BrowserAwarePageExtractor.extract: starting browser page extraction")
		self._seenTextSignatures.clear()
		browserInterceptor = self._target_resolver.resolve(context)
		bestSnapshot = None
		bestScore = -1
		bestEffortSnapshot = None
		bestEffortScore = -1
		activeProviders = [provider for provider in self._candidateProviders if provider.supports(context)]
		log.debug(
			"BrowserAwarePageExtractor.extract: active providers=%s",
			", ".join(provider.name for provider in activeProviders) or "<none>",
		)
		log.debug("BrowserAwarePageExtractor.extract: browserInterceptor=%s", self._describeObject(browserInterceptor))

		if browserInterceptor is not None:
			log.debug("BrowserAwarePageExtractor.extract: evaluating browser treeInterceptor first")
			browserRoot = self._browserRootFromInterceptor(browserInterceptor)
			snapshot = self._buildSnapshot(browserRoot, context, sourceName="browserTreeInterceptor")
			if snapshot is not None:
				score = self._candidateScore(browserRoot, context, snapshot, "browserTreeInterceptor", browserInterceptor)
				bestSnapshot = snapshot
				bestScore = score
				log.debug(f"Browser Assistant: browserTreeInterceptor candidate score={score}")
			else:
				bestEffortSnapshot, bestEffortScore = self._bestEffortSnapshot(
					browserRoot,
					context,
					sourceName="browserTreeInterceptor",
					browserInterceptor=browserInterceptor,
					currentBest=bestEffortSnapshot,
					currentScore=bestEffortScore,
				)

		for provider in activeProviders:
			log.debug("BrowserAwarePageExtractor.extract: iterating provider=%s", provider.name)
			seenCandidates: set[int] = set()
			for candidate in provider.iterCandidates(context):
				identity = id(candidate)
				if candidate is None or identity in seenCandidates:
					continue
				seenCandidates.add(identity)
				log.debug(
					"BrowserAwarePageExtractor.extract: provider=%s yielded candidate=%s",
					provider.name,
					self._describeObject(candidate),
				)

				if not self._shouldInspectCandidate(candidate, context, provider.name, browserInterceptor):
					log.debug(
						"BrowserAwarePageExtractor.extract: provider=%s candidate rejected by browser relevance heuristic",
						provider.name,
					)
					continue

				text = self._extractText(candidate)
				normalized = self._normalizeText(text)
				log.debug(
					"BrowserAwarePageExtractor.extract: provider=%s normalized text length=%d",
					provider.name,
					len(normalized),
				)
				if not self._isMeaningfulText(normalized):
					log.debug(
						"BrowserAwarePageExtractor.extract: provider=%s candidate rejected by text quality heuristic",
						provider.name,
					)
					bestEffortSnapshot, bestEffortScore = self._bestEffortSnapshot(
						candidate,
						context,
						sourceName=provider.name,
						browserInterceptor=browserInterceptor,
						currentBest=bestEffortSnapshot,
						currentScore=bestEffortScore,
						normalizedText=normalized,
					)
					continue

				trimmedText, truncated = self._trimText(normalized)
				textSignature = self._textSignature(trimmedText)
				if textSignature in self._seenTextSignatures:
					log.debug(
						"BrowserAwarePageExtractor.extract: provider=%s duplicate text content skipped",
						provider.name,
					)
					continue
				self._seenTextSignatures.add(textSignature)

				snapshot = self._buildSnapshot(candidate, context, sourceName=provider.name, trimmedText=trimmedText, truncated=truncated)
				if snapshot is not None:
					score = self._candidateScore(candidate, context, snapshot, provider.name, browserInterceptor)
					log.debug(
						"BrowserAwarePageExtractor.extract: provider=%s candidate score=%d snapshot=%s",
						provider.name,
						score,
						self._describeSnapshot(snapshot),
					)
					if score > bestScore:
						log.debug(
							"BrowserAwarePageExtractor.extract: provider=%s became new best candidate score=%d",
							provider.name,
						score,
						)
						bestSnapshot = snapshot
						bestScore = score

		if bestSnapshot is not None:
			log.debug(
				"BrowserAwarePageExtractor.extract: returning best snapshot score=%d snapshot=%s",
				bestScore,
				self._describeSnapshot(bestSnapshot),
			)
			return bestSnapshot

		if bestEffortSnapshot is not None:
			log.debug(
				"BrowserAwarePageExtractor.extract: falling back to best-effort snapshot score=%d snapshot=%s",
				bestEffortScore,
				self._describeSnapshot(bestEffortSnapshot),
			)
			return bestEffortSnapshot

		raise PageExtractionError(
			"Unable to read enough text from the current page. Move focus into the document and try again."
		)


	def _resolveBrowserTreeInterceptor(self, context: CandidateExtractionContext):
		if self._isUsableTreeInterceptor(context.focusTreeInterceptor):
			log.debug("BrowserAwarePageExtractor._resolveBrowserTreeInterceptor: using focus treeInterceptor")
			return context.focusTreeInterceptor

		focus = context.focus
		if focus is not None and treeInterceptorHandler is not None:
			try:
				resolved = treeInterceptorHandler.getTreeInterceptor(focus)
				if self._isUsableTreeInterceptor(resolved):
					log.debug(
						"BrowserAwarePageExtractor._resolveBrowserTreeInterceptor: resolved treeInterceptor from focus handler=%s",
						self._describeObject(resolved),
					)
					return resolved
			except Exception:
				log.debug("BrowserAwarePageExtractor._resolveBrowserTreeInterceptor: focus handler lookup failed", exc_info=True)

		if focus is not None:
			interceptor = getattr(focus, "treeInterceptor", None)
			if self._isUsableTreeInterceptor(interceptor):
				log.debug(
					"BrowserAwarePageExtractor._resolveBrowserTreeInterceptor: resolved treeInterceptor from focus=%s",
					self._describeObject(interceptor),
				)
				return interceptor

		if focus is not None and treeInterceptorHandler is not None:
			try:
				resolved = treeInterceptorHandler.getTreeInterceptor(focus)
				if self._isUsableTreeInterceptor(resolved):
					log.debug(
						"BrowserAwarePageExtractor._resolveBrowserTreeInterceptor: resolved treeInterceptor from retry handler=%s",
						self._describeObject(resolved),
					)
					return resolved
			except Exception:
				log.debug("BrowserAwarePageExtractor._resolveBrowserTreeInterceptor: retry handler lookup failed", exc_info=True)

		for obj in context.focusAncestors:
			interceptor = getattr(obj, "treeInterceptor", None)
			if self._isUsableTreeInterceptor(interceptor):
				log.debug(
					"BrowserAwarePageExtractor._resolveBrowserTreeInterceptor: resolved treeInterceptor from focus ancestor=%s",
					self._describeObject(obj),
				)
				return interceptor

		for candidate in (context.navigator, context.foreground):
			if candidate is None:
				continue
			if treeInterceptorHandler is not None:
				try:
					resolved = treeInterceptorHandler.getTreeInterceptor(candidate)
					if self._isUsableTreeInterceptor(resolved):
						log.debug(
							"BrowserAwarePageExtractor._resolveBrowserTreeInterceptor: resolved treeInterceptor from %s handler=%s",
							"navigator" if candidate is context.navigator else "foreground",
							self._describeObject(resolved),
						)
						return resolved
				except Exception:
					log.debug(
						"BrowserAwarePageExtractor._resolveBrowserTreeInterceptor: %s handler lookup failed",
						"navigator" if candidate is context.navigator else "foreground",
						exc_info=True,
					)
			interceptor = getattr(candidate, "treeInterceptor", None)
			if self._isUsableTreeInterceptor(interceptor):
				log.debug(
					"BrowserAwarePageExtractor._resolveBrowserTreeInterceptor: resolved treeInterceptor from %s object=%s",
					"navigator" if candidate is context.navigator else "foreground",
					self._describeObject(interceptor),
				)
				return interceptor

		log.debug("BrowserAwarePageExtractor._resolveBrowserTreeInterceptor: no usable treeInterceptor found")
		return None

	def _browserRootFromInterceptor(self, interceptor: object) -> object:
		root = getattr(interceptor, "rootNVDAObject", None)
		if root is not None:
			return root
		return interceptor

	def _isUsableTreeInterceptor(self, interceptor: object | None) -> bool:
		return is_usable_tree_interceptor(interceptor)

	def _buildSnapshot(
		self,
		obj: object,
		context: CandidateExtractionContext,
		sourceName: str,
		trimmedText: str | None = None,
		truncated: bool | None = None,
	):
		if trimmedText is None or truncated is None:
			text = self._extractText(obj)
			normalized = self._normalizeText(text)
			log.debug(
				f"Browser Assistant: source={sourceName} normalized text length={len(normalized)}"
			)
			if not self._isMeaningfulText(normalized):
				log.debug("Browser Assistant: candidate rejected by text quality heuristic")
				return None

			trimmedText, truncated = self._trimText(normalized)
			textSignature = self._textSignature(trimmedText)
			if textSignature in self._seenTextSignatures:
				log.debug("Browser Assistant: duplicate text content skipped")
				return None
			self._seenTextSignatures.add(textSignature)

		headings, links, buttons, landmarks, inputs, comboboxes, checkboxes, radios = self._extractStructuredInfo(obj)

		log.debug(
			f"Browser Assistant: selected source={sourceName} candidate={type(obj).__module__}.{type(obj).__name__}"
		)
		log.debug(
			"Browser Assistant: snapshot counts=headings=%d links=%d buttons=%d landmarks=%d",
			len(headings),
			len(links),
			len(buttons),
			len(landmarks),
		)
		return BrowserExtractionSnapshot(
			source="browser",
			title=self._extractTitle(obj, context),
			appTitle=self._extractAppTitle(context),
			text=trimmedText,
			truncated=truncated,
			headings=headings,
			links=links,
			buttons=buttons,
			landmarks=landmarks,
			inputs=inputs,
			comboboxes=comboboxes,
			checkboxes=checkboxes,
			radios=radios,
		)

	def _snapshotScore(self, snapshot: BrowserExtractionSnapshot | None) -> int:
		if snapshot is None:
			return -1
		return (
			len(snapshot.headings)
			+ len(snapshot.links)
			+ len(snapshot.buttons)
			+ len(snapshot.landmarks)
			+ len(snapshot.inputs)
			+ len(snapshot.comboboxes) * 2
			+ len(snapshot.checkboxes)
			+ len(snapshot.radios)
		)

	def _bestEffortSnapshot(
		self,
		obj: object,
		context: CandidateExtractionContext,
		sourceName: str,
		browserInterceptor: object | None,
		currentBest: BrowserExtractionSnapshot | None,
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

		headings, links, buttons, landmarks, inputs, comboboxes, checkboxes, radios = self._extractStructuredInfo(obj)
		snapshot = BrowserExtractionSnapshot(
			source="browser",
			title=self._extractTitle(obj, context),
			appTitle=self._extractAppTitle(context),
			text=trimmedText,
			truncated=truncated,
			headings=headings,
			links=links,
			buttons=buttons,
			landmarks=landmarks,
			inputs=inputs,
			comboboxes=comboboxes,
			checkboxes=checkboxes,
			radios=radios,
		)
		score = self._candidateScore(obj, context, snapshot, sourceName, browserInterceptor)
		score += min(len(trimmedText), 500) // 25
		if score > currentScore:
			log.debug(
				f"Browser Assistant: selected best-effort source={sourceName} candidate={type(obj).__module__}.{type(obj).__name__} score={score}"
			)
			return snapshot, score
		return currentBest, currentScore

	def _candidateScore(
		self,
		obj: object,
		context: CandidateExtractionContext,
		snapshot: BrowserExtractionSnapshot,
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

		score += len(snapshot.inputs)
		score += len(snapshot.comboboxes) * 2
		score += len(snapshot.checkboxes)
		score += len(snapshot.radios)

		if context.focus is obj:
			score += 5

		return score

	def _shouldInspectCandidate(
		self,
		candidate: object,
		context: CandidateExtractionContext,
		sourceName: str,
		browserInterceptor: object | None,
	) -> bool:
		if not self._isBrowserContext(context):
			return True
		if sourceName == "browserTreeInterceptor":
			return True
		if self._sharesBrowserDocument(candidate, browserInterceptor):
			return True
		if self._looksLikeDocumentObject(candidate):
			return True
		if candidate is context.focus and context.focusTreeInterceptor is None:
			return True
		return False

	def _isBrowserContext(self, context: CandidateExtractionContext) -> bool:
		if context.appName in self._BROWSER_APP_NAMES:
			return True
		if context.focus is not None and self._looksLikeDocumentObject(context.focus):
			return True
		if self._isUsableTreeInterceptor(context.focusTreeInterceptor):
			return self._looksLikeBrowserInterceptor(context.focusTreeInterceptor)
		return False

	def _looksLikeBrowserInterceptor(self, interceptor: object) -> bool:
		type_name = type(interceptor).__name__.lower()
		return any(token in type_name for token in ("vbuf", "mshtml", "chrome", "chromium", "web", "browser"))

	def _sharesBrowserDocument(self, obj: object, browserInterceptor: object | None) -> bool:
		if browserInterceptor is None:
			return False
		if obj is browserInterceptor:
			return True

		objInterceptor = getattr(obj, "treeInterceptor", None)
		if objInterceptor is browserInterceptor:
			return True

		browserRoot = getattr(browserInterceptor, "rootNVDAObject", None)
		if obj is browserRoot:
			return True

		objRoot = getattr(obj, "rootNVDAObject", None)
		return objRoot is not None and objRoot is browserRoot

	def _looksLikeDocumentObject(self, obj: object) -> bool:
		roleText = str(getattr(obj, "role", "")).upper()
		typeName = type(obj).__name__.lower()
		return any(token in roleText for token in ("DOCUMENT", "ARTICLE", "INTERNALFRAME", "WEBVIEW")) or any(
			token in typeName for token in ("document", "web", "chromium")
		)

	def _hasMainContentLandmark(self, snapshot: BrowserExtractionSnapshot) -> bool:
		for landmark in snapshot.landmarks:
			normalized = landmark.strip().lower()
			if any(token in normalized for token in ("main", "content", "article", "feed")):
				return True
		return False

	def _extractText(self, obj: object):
		return extract_text_from_object(obj, self._text_extractor)

	def _extractionTargets(self, obj: object):
		yield obj
		for attr in ("rootNVDAObject", "parent", "next", "previous"):
			try:
				target = getattr(obj, attr, None)
			except Exception:
				target = None
			if target is not None:
				yield target

	def _extractStructuredInfo(self, obj: object):
		headings, links, buttons, landmarks, inputs, comboboxes, checkboxes, radios = self._field_parser.extract_structured_info(obj)
		return headings, links, buttons, landmarks, inputs, comboboxes, checkboxes, radios

	def _dedupe_headings(self, headings: list[tuple[int | None, str]]) -> tuple[tuple[int | None, str], ...]:
		seen: set[tuple[int | None, str]] = set()
		unique: list[tuple[int | None, str]] = []
		for heading in headings:
			if heading not in seen:
				seen.add(heading)
				unique.append(heading)
		return tuple(unique)

	def _extractTitle(self, obj: object, context: CandidateExtractionContext) -> str:
		return extract_title(obj, context)

	def _extractAppTitle(self, context: CandidateExtractionContext) -> str:
		return extract_app_title(context)

	def _normalizeText(self, text: str) -> str:
		return normalize_extracted_text(text)

	def _isMeaningfulText(self, text: str) -> bool:
		return is_meaningful_text(text)

	def _trimText(self, text: str) -> tuple[str, bool]:
		return trim_text(text)

	def _textSignature(self, text: str) -> str:
		return text_signature(text)

	def _describeObject(self, obj: object | None) -> str:
		if obj is None:
			return "None"
		return f"{type(obj).__module__}.{type(obj).__name__}"

	def _describeSnapshot(self, snapshot: BrowserExtractionSnapshot | None) -> str:
		if snapshot is None:
			return "None"
		return (
			f"BrowserExtractionSnapshot(title={snapshot.title!r}, appTitle={snapshot.appTitle!r}, "
			f"text_len={len(snapshot.text)}, truncated={snapshot.truncated}, "
			f"headings={len(snapshot.headings)}, links={len(snapshot.links)}, "
			f"buttons={len(snapshot.buttons)}, landmarks={len(snapshot.landmarks)})"
		)
