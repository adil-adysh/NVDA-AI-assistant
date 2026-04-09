# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
import hashlib
import re
from collections.abc import Sequence
from typing import Any, cast

import api
from logHandler import log
from textInfos import POSITION_ALL, POSITION_CARET

try:
    import treeInterceptorHandler
except Exception:  # pragma: no cover
    treeInterceptorHandler = None

from .app_extractors import CandidateProvider, ExtractionContext, buildDefaultCandidateProviders
from .models import PageSnapshot

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
        super().__init__()
        log.debug("BrowserAwarePageExtractor initialized with %d candidate providers", len(candidateProviders or []))
        super().__init__()
        self._seenTextSignatures: set[str] = set()
        self._candidateProviders = tuple(candidateProviders or buildDefaultCandidateProviders())

    def extract(self):
        self._seenTextSignatures.clear()
        context = self._buildContext()
        browserInterceptor = self._resolveBrowserTreeInterceptor(context)
        bestSnapshot = None
        bestScore = -1
        bestEffortSnapshot = None
        bestEffortScore = -1
        activeProviders = [provider for provider in self._candidateProviders if provider.supports(context)]
        log.debug(
            f"Browser Assistant: active providers={','.join(provider.name for provider in activeProviders)}"
        )

        if browserInterceptor is not None:
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
            seenCandidates: set[int] = set()
            for candidate in provider.iterCandidates(context):
                identity = id(candidate)
                if candidate is None or identity in seenCandidates:
                    continue
                seenCandidates.add(identity)

                if not self._shouldInspectCandidate(candidate, context, provider.name, browserInterceptor):
                    log.debug("Browser Assistant: candidate rejected by browser relevance heuristic")
                    continue

                log.debug(
                    f"Browser Assistant: provider={provider.name} candidate={type(candidate).__module__}.{type(candidate).__name__}"
                )
                text = self._extractText(candidate)
                normalized = self._normalizeText(text)
                log.debug(
                    f"Browser Assistant: provider={provider.name} normalized text length={len(normalized)}"
                )
                if not self._isMeaningfulText(normalized):
                    log.debug("Browser Assistant: candidate rejected by text quality heuristic")
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
                    log.debug("Browser Assistant: duplicate text content skipped")
                    continue
                self._seenTextSignatures.add(textSignature)

                snapshot = self._buildSnapshot(candidate, context, sourceName=provider.name, trimmedText=trimmedText, truncated=truncated)
                if snapshot is not None:
                    score = self._candidateScore(candidate, context, snapshot, provider.name, browserInterceptor)
                    log.debug(f"Browser Assistant: provider={provider.name} candidate score={score}")
                    if score > bestScore:
                        bestSnapshot = snapshot
                        bestScore = score

        if bestSnapshot is not None:
            return bestSnapshot

        if bestEffortSnapshot is not None:
            log.debug("Browser Assistant: falling back to best-effort snapshot")
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
            "BrowserAwarePageExtractor context focus=%s ancestors=%d navigator=%s foreground=%s",
            type(focus).__name__ if focus is not None else None,
            len(focusAncestors),
            type(navigator).__name__ if navigator is not None else None,
            type(foreground).__name__ if foreground is not None else None,
        )

        appName = None
        appModule = getattr(focus, "appModule", None) if focus is not None else None
        maybeName = getattr(appModule, "appName", None) if appModule is not None else None
        if isinstance(maybeName, str) and maybeName.strip():
            appName = maybeName.strip().lower()

        return ExtractionContext(
            focus=focus,
            focusTreeInterceptor=focusTreeInterceptor,
            focusAncestors=focusAncestors,
            navigator=navigator,
            foreground=foreground,
            appName=appName,
        )

    def _resolveBrowserTreeInterceptor(self, context: ExtractionContext):
        if self._isUsableTreeInterceptor(context.focusTreeInterceptor):
            log.debug("BrowserAwarePageExtractor using focus treeInterceptor")
            return context.focusTreeInterceptor

        focus = context.focus
        if focus is not None and treeInterceptorHandler is not None:
            try:
                resolved = treeInterceptorHandler.getTreeInterceptor(focus)
                if self._isUsableTreeInterceptor(resolved):
                    return resolved
            except Exception:
                pass

        if focus is not None:
            interceptor = getattr(focus, "treeInterceptor", None)
            if self._isUsableTreeInterceptor(interceptor):
                return interceptor

        for obj in context.focusAncestors:
            interceptor = getattr(obj, "treeInterceptor", None)
            if self._isUsableTreeInterceptor(interceptor):
                log.debug("BrowserAwarePageExtractor resolved treeInterceptor from focus ancestors")
                return interceptor

        log.debug("BrowserAwarePageExtractor did not find a usable treeInterceptor")
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

        headings, links, buttons, landmarks = self._extractStructuredInfo(obj)

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
        )

    def _snapshotScore(self, snapshot: PageSnapshot | None) -> int:
        if snapshot is None:
            return -1
        return len(snapshot.headings) + len(snapshot.links) + len(snapshot.buttons) + len(snapshot.landmarks)

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

        headings, links, buttons, landmarks = self._extractStructuredInfo(obj)
        snapshot = PageSnapshot(
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

        for position in (POSITION_ALL, POSITION_CARET):
            try:
                info = cast(Any, obj).makeTextInfo(position)
                text = getattr(info, "text", None)
                if isinstance(text, str) and text.strip():
                    return text
            except Exception:
                continue

        return None

    def _extractStructuredInfo(self, obj: object):
        headings: list[tuple[int | None, str]] = []
        links: list[str] = []
        buttons: list[str] = []
        landmarks: list[str] = []

        seenHeadings: set[tuple[int | None, str]] = set()
        seenLinks: set[str] = set()
        seenButtons: set[str] = set()
        seenLandmarks: set[str] = set()
        for target in self._structuredTargets(obj):
            quickNavSource = self._quickNavSource(target)
            if quickNavSource is None:
                continue

            for item in self._iterNodesByType(quickNavSource, "heading"):
                text = self._nodeText(item, preferLabel=False)
                if not text:
                    continue
                level = getattr(item, "level", None)
                headingEntry = (level if isinstance(level, int) else None, text)
                if headingEntry in seenHeadings:
                    continue
                seenHeadings.add(headingEntry)
                headings.append(headingEntry)

            for item in self._iterNodesByType(quickNavSource, "link"):
                text = self._nodeText(item, preferLabel=False)
                if text:
                    if text in seenLinks:
                        continue
                    seenLinks.add(text)
                    links.append(text)

            for item in self._iterNodesByType(quickNavSource, "button"):
                text = self._nodeText(item, preferLabel=False)
                if text:
                    if text in seenButtons:
                        continue
                    seenButtons.add(text)
                    buttons.append(text)

            for item in self._iterNodesByType(quickNavSource, "landmark"):
                text = self._nodeText(item, preferLabel=True)
                if text:
                    if text in seenLandmarks:
                        continue
                    seenLandmarks.add(text)
                    landmarks.append(text)

        return tuple(headings), tuple(links), tuple(buttons), tuple(landmarks)

    def _structuredTargets(self, obj: object):
        seen: set[int] = set()
        for candidate in (obj, getattr(obj, "rootNVDAObject", None)):
            if candidate is None:
                continue
            candidateId = id(candidate)
            if candidateId in seen:
                continue
            seen.add(candidateId)
            yield candidate

        if hasattr(obj, "makeTextInfo"):
            try:
                info = cast(Any, obj).makeTextInfo(POSITION_CARET)
            except Exception:
                info = None
            if info is not None:
                caretObj = getattr(info, "NVDAObjectAtStart", None)
                if caretObj is not None:
                    caretId = id(caretObj)
                    if caretId not in seen:
                        seen.add(caretId)
                        yield caretObj

    def _extractionTargets(self, obj: object):
        seen: set[int] = set()
        for candidate in (obj, getattr(obj, "rootNVDAObject", None)):
            if candidate is None:
                continue
            candidateId = id(candidate)
            if candidateId in seen:
                continue
            seen.add(candidateId)
            yield candidate

        if hasattr(obj, "makeTextInfo"):
            try:
                info = cast(Any, obj).makeTextInfo(POSITION_CARET)
            except Exception:
                info = None
            if info is not None:
                caretObj = getattr(info, "NVDAObjectAtStart", None)
                if caretObj is not None:
                    caretId = id(caretObj)
                    if caretId not in seen:
                        seen.add(caretId)
                        yield caretObj

    def _iterNodesByType(self, ti: object, nodeType: str):
        if not hasattr(ti, "_iterNodesByType"):
            return tuple()
        try:
            return tuple(cast(Any, ti)._iterNodesByType(nodeType))
        except Exception:
            return tuple()

    def _quickNavSource(self, obj: object):
        if hasattr(obj, "_iterNodesByType"):
            return obj

        interceptor = getattr(obj, "treeInterceptor", None)
        if hasattr(interceptor, "_iterNodesByType"):
            return interceptor

        root = getattr(obj, "rootNVDAObject", None)
        rootInterceptor = getattr(root, "treeInterceptor", None) if root is not None else None
        if hasattr(rootInterceptor, "_iterNodesByType"):
            return rootInterceptor

        return None

    def _nodeText(self, item: object, preferLabel: bool = False):
        if preferLabel:
            label = self._itemLabel(item)
            if label:
                return label

        try:
            textInfo = getattr(item, "textInfo", None)
            if textInfo is not None:
                text = getattr(textInfo, "text", None)
                if isinstance(text, str) and text.strip():
                    return self._normalizeText(text)
        except Exception:
            pass

        label = self._itemLabel(item)
        if label:
            return label

        return None

    def _itemLabel(self, item: object):
        try:
            label = getattr(item, "label", None)
            if isinstance(label, str) and label.strip():
                return label.strip()
        except Exception:
            pass

        return None

    def _isMeaningfulText(self, text: str):
        if len(text) < MIN_PAGE_TEXT_CHARS:
            return False

        lines = [line for line in text.split("\n") if line.strip()]
        if len(lines) < 5:
            return False

        averageLength = sum(len(line) for line in lines) / len(lines)
        if averageLength <= 8 and len(text) < 1000:
            return False

        distinctLineCount = len({line.lower() for line in lines})
        if distinctLineCount <= max(2, len(lines) // 5):
            return False

        log.debug(
            f"Browser Assistant: text metrics length={len(text)} lines={len(lines)} averageLineLength={averageLength:.2f} distinctLines={distinctLineCount}"
        )

        return True

    def _normalizeText(self, text: str):
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        normalizedLines = []
        for line in text.split("\n"):
            compactLine = re.sub(r"\s+", " ", line).strip()
            if compactLine:
                normalizedLines.append(compactLine)
        return "\n".join(normalizedLines)

    def _trimText(self, text: str):
        if len(text) <= MAX_PAGE_TEXT_CHARS:
            return text, False

        headLength = int(MAX_PAGE_TEXT_CHARS * 0.8)
        tailLength = MAX_PAGE_TEXT_CHARS - headLength - len(_ELLIPSIS_BLOCK)
        if tailLength < 0:
            tailLength = 0

        trimmed = text[:headLength].rstrip()
        if tailLength:
            trimmed += _ELLIPSIS_BLOCK + text[-tailLength:].lstrip()
        return trimmed, True

    def _extractTitle(self, obj: object, context: ExtractionContext):
        root = getattr(obj, "rootNVDAObject", None)
        for candidate in (root, obj, context.foreground, context.focus):
            if candidate is None:
                continue
            try:
                name = getattr(candidate, "name", None)
            except Exception:
                name = None
            if not isinstance(name, str):
                continue

            cleaned = name.strip()
            if not cleaned:
                continue

            if cleaned.lower() in {"pane", "document", "application"}:
                continue

            return cleaned
        return "Current page"

    def _extractAppTitle(self, context: ExtractionContext) -> str:
        for candidate in (context.foreground, context.focus):
            if candidate is None:
                continue
            title = None
            try:
                title = getattr(candidate, "windowText", None)
            except Exception:
                title = None
            if not isinstance(title, str) or not title.strip():
                try:
                    title = getattr(candidate, "name", None)
                except Exception:
                    title = None
            if not isinstance(title, str):
                continue
            cleaned = title.strip()
            if not cleaned:
                continue
            if cleaned.lower() in {"pane", "document", "application"}:
                continue
            return cleaned
        return ""

    def _getFocusObjectSafe(self):
        try:
            return api.getFocusObject()
        except Exception:
            return None

    def _getNavigatorObjectSafe(self):
        try:
            return api.getNavigatorObject()
        except Exception:
            return None

    def _getFocusAncestorsSafe(self):
        try:
            return tuple(api.getFocusAncestors())
        except Exception:
            return tuple()

    def _getForegroundObjectSafe(self):
        try:
            return api.getForegroundObject()
        except Exception:
            return None

    def _textSignature(self, text: str):
        return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()
