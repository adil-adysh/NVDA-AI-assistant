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
