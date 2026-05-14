# -*- coding: utf-8 -*-
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CandidateExtractionContext:
	focus: object | None
	focusTreeInterceptor: object | None
	focusAncestors: tuple[object, ...]
	navigator: object | None
	foreground: object | None
	appName: str | None


class CandidateProvider(ABC):
	name: str = "unknown"

	@abstractmethod
	def supports(self, context: CandidateExtractionContext) -> bool:
		raise NotImplementedError

	@abstractmethod
	def iterCandidates(self, context: CandidateExtractionContext) -> Any:
		raise NotImplementedError


def is_usable_tree_interceptor(interceptor: object | None) -> bool:
	"""Check whether an NVDA tree interceptor object is alive, ready, and usable for text extraction."""
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
