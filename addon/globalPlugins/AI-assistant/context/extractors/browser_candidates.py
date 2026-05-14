# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

import api
import controlTypes
from logHandler import log
from textInfos import POSITION_CARET

try:
	import treeInterceptorHandler
except Exception:  # pragma: no cover
	treeInterceptorHandler = None

from .candidate_base import CandidateProvider, CandidateExtractionContext, is_usable_tree_interceptor


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

	def supports(self, context: CandidateExtractionContext) -> bool:
		log.debug(
			"BrowserCandidateProvider.supports: appName=%s focus=%s",
			context.appName,
			self._describeObject(context.focus),
		)
		interceptor = self._resolveTreeInterceptor(context)
		if interceptor is not None:
			log.debug(
				"BrowserCandidateProvider.supports: browser treeInterceptor available=%s",
				self._describeObject(interceptor),
			)
			return True

		if context.appName not in self._BROWSER_APP_NAMES:
			log.debug("BrowserCandidateProvider.supports: rejected appName=%s", context.appName)
			return False
		log.debug("BrowserCandidateProvider.supports: accepted via browser app name")
		return context.focus is not None

	def iterCandidates(self, context: CandidateExtractionContext) -> Any:
		focus = context.focus
		if focus is None:
			log.debug("BrowserCandidateProvider.iterCandidates: no focus object")
			return

		log.debug(
			"BrowserCandidateProvider.iterCandidates: focus=%s navigator=%s foreground=%s",
			self._describeObject(context.focus),
			self._describeObject(context.navigator),
			self._describeObject(context.foreground),
		)

		interceptor = self._resolveTreeInterceptor(context)
		if interceptor is not None:
			log.debug("BrowserCandidateProvider.iterCandidates: yielding treeInterceptor=%s", self._describeObject(interceptor))
			yield interceptor
			root = self._rootObjectFromTreeInterceptor(interceptor)
			if root is not None and root is not interceptor:
				log.debug(
					"BrowserCandidateProvider.iterCandidates: yielding interceptor root=%s role=%s name=%s",
					self._describeObject(root),
					getattr(root, "role", None),
					getattr(root, "name", None),
				)
				yield root

			caretObj = self._caretObjectFromTreeInterceptor(interceptor)
			if caretObj is not None:
				log.debug("BrowserCandidateProvider.iterCandidates: yielding caret object=%s", self._describeObject(caretObj))
				yield caretObj

		document = self._documentFromFocus(focus, context)
		if document is not None:
			log.debug("BrowserCandidateProvider.iterCandidates: yielding document=%s", self._describeObject(document))
			yield document

		log.debug("BrowserCandidateProvider.iterCandidates: yielding focus=%s", self._describeObject(focus))
		yield focus

	def _resolveTreeInterceptor(self, context: CandidateExtractionContext) -> object | None:
		direct = context.focusTreeInterceptor
		if self._isUsableTreeInterceptor(direct):
			log.debug("BrowserCandidateProvider._resolveTreeInterceptor: using focus treeInterceptor=%s", self._describeObject(direct))
			return direct

		focus = context.focus
		if focus is not None and treeInterceptorHandler is not None:
			try:
				resolved = treeInterceptorHandler.getTreeInterceptor(focus)
				if self._isUsableTreeInterceptor(resolved):
					log.debug("BrowserCandidateProvider._resolveTreeInterceptor: resolved via handler=%s", self._describeObject(resolved))
					return resolved
			except Exception:
				log.debug("BrowserCandidateProvider._resolveTreeInterceptor: handler lookup failed", exc_info=True)
				pass

		for obj in reversed(context.focusAncestors):
			interceptor = getattr(obj, "treeInterceptor", None)
			if self._isUsableTreeInterceptor(interceptor):
				log.debug("BrowserCandidateProvider._resolveTreeInterceptor: using focus ancestor=%s", self._describeObject(obj))
				return interceptor

		for candidate in (context.navigator, context.foreground):
			if candidate is None:
				continue
			interceptor = getattr(candidate, "treeInterceptor", None)
			if self._isUsableTreeInterceptor(interceptor):
				log.debug(
					"BrowserCandidateProvider._resolveTreeInterceptor: using %s treeInterceptor=%s",
					"navigator" if candidate is context.navigator else "foreground",
					self._describeObject(interceptor),
				)
				return interceptor

		return None

	def _isUsableTreeInterceptor(self, interceptor: object | None) -> bool:
		if not is_usable_tree_interceptor(interceptor):
			return False
		root = getattr(interceptor, "rootNVDAObject", None)
		return root is not None

	def _rootObjectFromTreeInterceptor(self, interceptor: object) -> object | None:
		try:
			return getattr(interceptor, "rootNVDAObject", None)
		except Exception:
			return None

	def _caretObjectFromTreeInterceptor(self, interceptor: object) -> object | None:
		try:
			info = interceptor.makeTextInfo(POSITION_CARET)
		except Exception:
			return None

		try:
			candidate = getattr(info, "NVDAObjectAtStart", None)
		except Exception:
			candidate = None
		return candidate

	def _documentFromFocus(self, focus: object, context: CandidateExtractionContext) -> object | None:
		log.debug("BrowserCandidateProvider._documentFromFocus: focus=%s", self._describeObject(focus))
		try:
			ancestors = list(api.getFocusAncestors())
		except Exception:
			ancestors = []
		for obj in list(ancestors) + [focus]:
			role = getattr(obj, "role", None)
			if self._isDocumentRole(role):
				log.debug("BrowserCandidateProvider._documentFromFocus: using document ancestor=%s", self._describeObject(obj))
				return obj

		for candidate in (context.navigator, context.foreground):
			if candidate is None:
				continue
			role = getattr(candidate, "role", None)
			if self._isDocumentRole(role):
				log.debug(
					"BrowserCandidateProvider._documentFromFocus: using %s document candidate=%s",
					"navigator" if candidate is context.navigator else "foreground",
					self._describeObject(candidate),
				)
				return candidate

		return None

	def _isDocumentRole(self, role: object) -> bool:
		try:
			if role == controlTypes.Role.DOCUMENT:
				return True
		except Exception:
			pass
		return "DOCUMENT" in str(role).upper()

	def _describeObject(self, obj: object | None) -> str:
		if obj is None:
			return "None"
		return f"{type(obj).__module__}.{type(obj).__name__}"
