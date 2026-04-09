# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportImplicitOverride=false
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, cast

import api
import controlTypes
from textInfos import POSITION_CARET

try:
    import treeInterceptorHandler
except Exception:  # pragma: no cover
    treeInterceptorHandler = None


@dataclass(frozen=True, slots=True)
class ExtractionContext:
    focus: object | None
    focusTreeInterceptor: object | None
    focusAncestors: tuple[object, ...]
    navigator: object | None
    foreground: object | None
    appName: str | None


class CandidateProvider(ABC):
    name: str = "unknown"

    @abstractmethod
    def supports(self, context: ExtractionContext) -> bool:
        raise NotImplementedError

    @abstractmethod
    def iterCandidates(self, context: ExtractionContext):
        raise NotImplementedError


class BrowserCandidateProvider(CandidateProvider):
    name = "browser"
    _BROWSER_APP_NAMES = {
        "chrome",
        "msedge",
        "firefox",
        "brave",
        "opera",
        "vivaldi",
    }

    def supports(self, context: ExtractionContext) -> bool:
        interceptor = self._resolveTreeInterceptor(context)
        if interceptor is not None:
            return True

        if context.appName not in self._BROWSER_APP_NAMES:
            return False
        return context.focus is not None

    def iterCandidates(self, context: ExtractionContext):
        focus = context.focus
        if focus is None:
            return

        interceptor = self._resolveTreeInterceptor(context)
        if interceptor is not None:
            yield interceptor

            root = getattr(interceptor, "rootNVDAObject", None)
            if root is not None:
                yield root

            caretObj = self._caretObjectFromTreeInterceptor(interceptor)
            if caretObj is not None:
                yield caretObj

        document = self._documentFromFocus(focus)
        if document is not None:
            yield document

        yield focus

    def _resolveTreeInterceptor(self, context: ExtractionContext):
        direct = context.focusTreeInterceptor
        if self._isUsableTreeInterceptor(direct):
            return direct

        focus = context.focus
        if focus is not None and treeInterceptorHandler is not None:
            try:
                resolved = treeInterceptorHandler.getTreeInterceptor(focus)
                if self._isUsableTreeInterceptor(resolved):
                    return resolved
            except Exception:
                pass

        for obj in context.focusAncestors:
            interceptor = getattr(obj, "treeInterceptor", None)
            if self._isUsableTreeInterceptor(interceptor):
                return interceptor

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

        root = getattr(interceptor, "rootNVDAObject", None)
        return root is not None

    def _caretObjectFromTreeInterceptor(self, interceptor: object):
        try:
            info = cast(Any, interceptor).makeTextInfo(POSITION_CARET)
        except Exception:
            return None

        try:
            candidate = getattr(info, "NVDAObjectAtStart", None)
        except Exception:
            candidate = None
        return candidate

    def _documentFromFocus(self, focus: object):
        try:
            ancestors = list(api.getFocusAncestors())
        except Exception:
            ancestors = []
        for obj in list(ancestors) + [focus]:
            role = getattr(obj, "role", None)
            if self._isDocumentRole(role):
                return obj
        return None

    def _isDocumentRole(self, role: object) -> bool:
        try:
            if role == controlTypes.Role.DOCUMENT:
                return True
        except Exception:
            pass
        return "DOCUMENT" in str(role).upper()


class TextAppCandidateProvider(CandidateProvider):
    name = "textApp"
    _TEXT_APP_NAMES = {
        "code",
        "notepad",
        "notepad++",
        "pwsh",
        "powershell",
        "cmd",
        "windowsterminal",
        "devenv",
    }

    def supports(self, context: ExtractionContext) -> bool:
        if context.appName in self._TEXT_APP_NAMES:
            return True
        focus = context.focus
        return focus is not None and hasattr(focus, "makeTextInfo")

    def iterCandidates(self, context: ExtractionContext):
        if context.focus is not None:
            yield context.focus
            parent = getattr(context.focus, "parent", None)
            if parent is not None:
                yield parent

        if context.navigator is not None:
            yield context.navigator

        if context.foreground is not None:
            yield context.foreground


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


def buildDefaultCandidateProviders() -> tuple[CandidateProvider, ...]:
    return (
        BrowserCandidateProvider(),
        TextAppCandidateProvider(),
        GenericCandidateProvider(),
    )
