# -*- coding: utf-8 -*-
from __future__ import annotations

import api
from .candidate_base import CandidateExtractionContext

try:
	import treeInterceptorHandler
except Exception:  # pragma: no cover
	treeInterceptorHandler = None


class BrowserTargetResolver:
	def resolve(self, context: CandidateExtractionContext) -> object | None:
		candidates = (
			context.focusTreeInterceptor,
			self._treeInterceptorFromFocus(context.focus),
			self._treeInterceptorFromAncestors(context.focusAncestors),
			self._treeInterceptorFromCandidate(context.navigator),
			self._treeInterceptorFromCandidate(context.foreground),
		)

		for candidate in candidates:
			if self._isUsableTreeInterceptor(candidate):
				return candidate

		focus = context.focus
		if focus is not None and self._hasDocumentRole(focus):
			return focus

		for candidate in (context.navigator, context.foreground):
			if candidate is not None and self._hasDocumentRole(candidate):
				return candidate

		if focus is not None:
			return focus

		return None

	def _treeInterceptorFromFocus(self, focus: object | None) -> object | None:
		if focus is None or treeInterceptorHandler is None:
			return None
		try:
			return treeInterceptorHandler.getTreeInterceptor(focus)
		except Exception:
			return None

	def _treeInterceptorFromAncestors(self, ancestors: tuple[object, ...]) -> object | None:
		for obj in ancestors:
			interceptor = getattr(obj, "treeInterceptor", None)
			if self._isUsableTreeInterceptor(interceptor):
				return interceptor
		return None

	def _treeInterceptorFromCandidate(self, candidate: object | None) -> object | None:
		if candidate is None:
			return None
		if treeInterceptorHandler is not None:
			try:
				resolved = treeInterceptorHandler.getTreeInterceptor(candidate)
				if self._isUsableTreeInterceptor(resolved):
					return resolved
			except Exception:
				pass
		return getattr(candidate, "treeInterceptor", None)

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

	def _hasDocumentRole(self, obj: object) -> bool:
		try:
			role = getattr(obj, "role", None)
			return role is not None and "DOCUMENT" in str(role).upper()
		except Exception:
			return False
