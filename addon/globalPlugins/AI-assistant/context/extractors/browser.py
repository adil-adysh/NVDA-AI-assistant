# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence

import api
import controlTypes
from logHandler import log
from textInfos import POSITION_ALL

try:
	import treeInterceptorHandler
except Exception:  # pragma: no cover
	treeInterceptorHandler = None

from ...context.types import PageSnapshot
from .candidates import CandidateProvider, ExtractionContext, buildDefaultCandidateProviders

MAX_PAGE_TEXT_CHARS = 120000
MIN_PAGE_TEXT_CHARS = 120

_ELLIPSIS_BLOCK = "\n\n[Content trimmed before summarization]\n\n"


class PageExtractionError(RuntimeError):
	pass


class BrowserAwarePageExtractor:
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
		self._candidateProviders = tuple(candidateProviders or buildDefaultCandidateProviders())

	def extract(self):
		log.debug("BrowserAwarePageExtractor.extract: starting browser page extraction")
		self._seenTextSignatures.clear()
		context = self._buildContext()
		browserInterceptor = self._resolveBrowserTreeInterceptor(context)
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
			snapshot = self._buildSnapshot(browserInterceptor, context, sourceName="browserTreeInterceptor")
			if snapshot is not None:
				score = self._candidateScore(browserInterceptor, context, snapshot, "browserTreeInterceptor", browserInterceptor)
				bestSnapshot = snapshot
				bestScore = score
				log.debug(f"Browser Assistant: browserTreeInterceptor candidate score={score}")
			else:
				bestEffortSnapshot, bestEffortScore = self._bestEffortSnapshot(
					browserInterceptor,
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

	def _buildContext(self) -> ExtractionContext:
		focus = self._getFocusObjectSafe()
		focusTreeInterceptor = getattr(focus, "treeInterceptor", None) if focus is not None else None
		focusAncestors = self._getFocusAncestorsSafe()
		navigator = self._getNavigatorObjectSafe()
		foreground = self._getForegroundObjectSafe()

		log.debug(
			"BrowserAwarePageExtractor._buildContext: focus=%s ancestors=%d navigator=%s foreground=%s",
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
			"BrowserAwarePageExtractor._buildContext: appName=%s focusTreeInterceptor=%s",
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
		try:
			return api.getFocusObject()
		except Exception:
			return None

	def _getFocusAncestorsSafe(self) -> tuple[object, ...]:
		try:
			ancestors = api.getFocusAncestors()
		except Exception:
			return ()
		if ancestors is None:
			return ()
		return tuple(ancestors)

	def _getNavigatorObjectSafe(self) -> object | None:
		try:
			return api.getNavigatorObject()
		except Exception:
			return None

	def _getForegroundObjectSafe(self) -> object | None:
		try:
			return api.getForegroundObject()
		except Exception:
			return None

	def _resolveBrowserTreeInterceptor(self, context: ExtractionContext):
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
				pass

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
				pass

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
					pass
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

	def _isUsableTreeInterceptor(self, interceptor: object | None) -> bool:
		if interceptor is None:
			return False
		if not hasattr(interceptor, "makeTextInfo"):
			return False

		try:
			isAlive = getattr(interceptor, "isAlive", True)
			if isAlive is False:
				return False
		except Exception:
			return False

		try:
			isReady = getattr(interceptor, "isReady", True)
			if isReady is False:
				return False
		except Exception:
			pass

		return True

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
		return PageSnapshot(
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

	def _snapshotScore(self, snapshot: PageSnapshot | None) -> int:
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
		context: ExtractionContext,
		sourceName: str,
		browserInterceptor: object | None,
		currentBest: PageSnapshot | None,
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
		snapshot = PageSnapshot(
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
		context: ExtractionContext,
		snapshot: PageSnapshot,
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
		context: ExtractionContext,
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

	def _isBrowserContext(self, context: ExtractionContext) -> bool:
		return context.appName in self._BROWSER_APP_NAMES or self._isUsableTreeInterceptor(context.focusTreeInterceptor)

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

	def _hasMainContentLandmark(self, snapshot: PageSnapshot) -> bool:
		for landmark in snapshot.landmarks:
			normalized = landmark.strip().lower()
			if any(token in normalized for token in ("main", "content", "article", "feed")):
				return True
		return False

	def _extractText(self, obj: object):
		for target in self._extractionTargets(obj):
			text = self._extractTextInfoText(target)
			if text:
				return text

		fragments = []
		for attr in ("name", "value", "description", "displayText"):
			try:
				value = getattr(obj, attr, None)
			except Exception:
				value = None
			if isinstance(value, str) and value.strip():
				fragments.append(value.strip())
		return "\n".join(fragments)

	def _extractTextInfoText(self, obj: object):
		if not hasattr(obj, "makeTextInfo"):
			return None
		try:
			textInfo = obj.makeTextInfo(POSITION_ALL)
		except Exception:
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
		textInfo = self._makeTextInfo(obj)
		if textInfo is None:
			return (), (), (), ()

		fields = self._makeTextWithFields(textInfo)
		if not fields:
			return (), (), (), ()

		headings, links, buttons, landmarks, inputs, comboboxes, checkboxes, radios = self._parseTextFields(fields)
		return tuple(headings), tuple(links), tuple(buttons), tuple(landmarks), tuple(inputs), tuple(comboboxes), tuple(checkboxes), tuple(radios)

	def _makeTextInfo(self, obj: object):
		if not hasattr(obj, "makeTextInfo"):
			return None
		try:
			return obj.makeTextInfo(POSITION_ALL)
		except Exception:
			return None

	def _makeTextWithFields(self, textInfo: object):
		if textInfo is None:
			return ()
		try:
			fields = getattr(textInfo, "getTextWithFields", None)
			if callable(fields):
				return fields() or ()
			return ()
		except Exception:
			return ()

	def _parseTextFields(self, fields: object):
		headings = []
		links = []
		buttons = []
		landmarks = []
		inputs = []
		comboboxes = []
		checkboxes = []
		radios = []
		stack: list[dict[str, object]] = []

		for item in fields:
			if isinstance(item, str):
				if stack:
					stack[-1]["text"].append(item)
				continue

			command = getattr(item, "command", None)
			field = getattr(item, "field", None)
			if command == "controlStart" and field is not None:
				if self._isHiddenField(field):
					continue
				stack.append(
					{
						"field": field,
						"text": [],
					}
				)
			elif command == "controlEnd" and stack:
				frame = stack.pop()
				label = self._normalizeCandidateText(" ".join(frame["text"]))
				if not label:
					label = self._explicitFieldName(frame["field"])
				if label:
					if self._isHeadingField(frame["field"]):
						level = self._headingLevel(frame["field"])
						headings.append((level, label))
					elif self._isButtonField(frame["field"]):
						buttons.append(label)
					elif self._isComboBoxField(frame["field"]):
						comboboxes.append(label)
					elif self._isCheckBoxField(frame["field"]):
						checkboxes.append(label)
					elif self._isRadioField(frame["field"]):
						radios.append(label)
					elif self._isInputField(frame["field"]):
						inputs.append(label)
					elif self._isLinkField(frame["field"]):
						links.append(label)
					elif self._isLandmarkField(frame["field"]):
						landmarks.append(label)
				if stack and label:
					stack[-1]["text"].append(label)

		return (
			self._dedupe_headings(headings),
			self._dedupe_strings(links),
			self._dedupe_strings(buttons),
			self._dedupe_strings(landmarks),
			self._dedupe_strings(inputs),
			self._dedupe_strings(comboboxes),
			self._dedupe_strings(checkboxes),
			self._dedupe_strings(radios),
		)

	def _normalizeCandidateText(self, text: str) -> str:
		text = re.sub(r"\s+", " ", text or "")
		return text.strip()

	def _explicitFieldName(self, field: object) -> str:
		if field is None:
			return ""
		value = self._fieldValue(field, "IAccessible2::attribute_explicit-name")
		if value:
			return self._normalizeCandidateText(str(value))
		value = self._fieldValue(field, "name")
		if value:
			return self._normalizeCandidateText(str(value))
		value = self._fieldValue(field, "IAccessible2::attribute_name-from")
		if value:
			return self._normalizeCandidateText(str(value))
		return ""

	def _fieldValue(self, field: object, key: str) -> object | None:
		try:
			return field.get(key)
		except Exception:
			return None

	def _headingLevel(self, field: object) -> int | None:
		tag = self._fieldValue(field, "IAccessible2::attribute_tag")
		if isinstance(tag, str):
			tag = tag.strip().lower()
			if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
				return int(tag[1])
		return None

	def _isHeadingField(self, field: object) -> bool:
		role = self._numericFieldRole(field)
		tag = self._fieldValue(field, "IAccessible2::attribute_tag")
		xml_role = self._fieldValue(field, "IAccessible2::attribute_xml-roles")
		return (
			role == controlTypes.Role.HEADING.value
			or isinstance(tag, str) and tag.strip().lower() in ("h1", "h2", "h3", "h4", "h5", "h6")
			or isinstance(xml_role, str) and "heading" in xml_role.strip().lower()
		)

	def _isButtonField(self, field: object) -> bool:
		role = self._numericFieldRole(field)
		tag = self._fieldValue(field, "IAccessible2::attribute_tag")
		xml_role = self._fieldValue(field, "IAccessible2::attribute_xml-roles")
		return (
			role in {
				controlTypes.Role.BUTTON.value,
				controlTypes.Role.MENUBUTTON.value,
				controlTypes.Role.TOGGLEBUTTON.value,
			}
			or isinstance(xml_role, str) and "button" in xml_role.strip().lower()
			or isinstance(tag, str) and tag.strip().lower() == "button"
		)

	def _isLinkField(self, field: object) -> bool:
		role = self._numericFieldRole(field)
		tag = self._fieldValue(field, "IAccessible2::attribute_tag")
		xml_role = self._fieldValue(field, "IAccessible2::attribute_xml-roles")
		return (
			role == controlTypes.Role.LINK.value
			or isinstance(xml_role, str) and "link" in xml_role.strip().lower()
			or isinstance(tag, str) and tag.strip().lower() == "a"
		)

	def _isComboBoxField(self, field: object) -> bool:
		role = self._numericFieldRole(field)
		tag = self._fieldValue(field, "IAccessible2::attribute_tag")
		xml_role = self._fieldValue(field, "IAccessible2::attribute_xml-roles")
		return (
			role == controlTypes.Role.COMBOBOX.value if hasattr(controlTypes.Role, 'COMBOBOX') else False
			or isinstance(xml_role, str) and "combobox" in xml_role.strip().lower()
			or isinstance(tag, str) and tag.strip().lower() in {"select", "combobox"}
		)

	def _isCheckBoxField(self, field: object) -> bool:
		role = self._numericFieldRole(field)
		tag = self._fieldValue(field, "IAccessible2::attribute_tag")
		xml_role = self._fieldValue(field, "IAccessible2::attribute_xml-roles")
		return (
			role == controlTypes.Role.CHECKBOX.value if hasattr(controlTypes.Role, 'CHECKBOX') else False
			or isinstance(xml_role, str) and "checkbox" in xml_role.strip().lower()
			or isinstance(tag, str) and tag.strip().lower() == "checkbox"
		)

	def _isRadioField(self, field: object) -> bool:
		role = self._numericFieldRole(field)
		tag = self._fieldValue(field, "IAccessible2::attribute_tag")
		xml_role = self._fieldValue(field, "IAccessible2::attribute_xml-roles")
		return (
			role == controlTypes.Role.RADIO.value if hasattr(controlTypes.Role, 'RADIO') else False
			or isinstance(xml_role, str) and "radio" in xml_role.strip().lower()
			or isinstance(tag, str) and tag.strip().lower() == "radio"
		)

	def _isInputField(self, field: object) -> bool:
		role = self._numericFieldRole(field)
		tag = self._fieldValue(field, "IAccessible2::attribute_tag")
		xml_role = self._fieldValue(field, "IAccessible2::attribute_xml-roles")
		return (
			role == controlTypes.Role.TEXT.value if hasattr(controlTypes.Role, 'TEXT') else False
			or isinstance(xml_role, str)
			and any(token in xml_role.strip().lower() for token in ("textbox", "searchbox", "spinbutton", "text"))
			or isinstance(tag, str)
			and tag.strip().lower() in {"input", "textarea", "textbox", "search"}
		)

	def _isLandmarkField(self, field: object) -> bool:
		role = self._numericFieldRole(field)
		tag = self._fieldValue(field, "IAccessible2::attribute_tag")
		xml_role = self._fieldValue(field, "IAccessible2::attribute_xml-roles")
		landmark = self._fieldValue(field, "landmark")
		if isinstance(xml_role, str) and xml_role.strip().lower() in {
			"banner",
			"complementary",
			"contentinfo",
			"form",
			"main",
			"navigation",
			"search",
		}:
			return True
		if isinstance(tag, str) and tag.strip().lower() in {
			"main",
			"nav",
			"banner",
			"complementary",
			"contentinfo",
			"search",
		}:
			return True
		if landmark is not None:
			return True
		return False

	def _numericFieldRole(self, field: object) -> int | None:
		role = self._fieldValue(field, "role")
		if isinstance(role, controlTypes.Role):
			return role.value
		if isinstance(role, int):
			return role
		if isinstance(role, str) and role.isdigit():
			return int(role)
		return None

	def _isHiddenField(self, field: object) -> bool:
		hidden = self._fieldValue(field, "isHidden")
		if hidden is True:
			return True
		if isinstance(hidden, str) and hidden.strip() in {"1", "true", "yes"}:
			return True
		return False

	def _dedupe_strings(self, items: list[str]) -> tuple[str, ...]:
		seen: set[str] = set()
		unique: list[str] = []
		for item in items:
			if item and item not in seen:
				seen.add(item)
				unique.append(item)
		return tuple(unique)

	def _dedupe_headings(self, headings: list[tuple[int | None, str]]) -> tuple[tuple[int | None, str], ...]:
		seen: set[tuple[int | None, str]] = set()
		unique: list[tuple[int | None, str]] = []
		for heading in headings:
			if heading not in seen:
				seen.add(heading)
				unique.append(heading)
		return tuple(unique)

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

	def _describeSnapshot(self, snapshot: PageSnapshot | None) -> str:
		if snapshot is None:
			return "None"
		return (
			f"PageSnapshot(title={snapshot.title!r}, appTitle={snapshot.appTitle!r}, "
			f"text_len={len(snapshot.text)}, truncated={snapshot.truncated}, "
			f"headings={len(snapshot.headings)}, links={len(snapshot.links)}, "
			f"buttons={len(snapshot.buttons)}, landmarks={len(snapshot.landmarks)})"
		)
