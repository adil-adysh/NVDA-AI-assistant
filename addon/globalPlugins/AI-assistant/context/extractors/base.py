# -*- coding: utf-8 -*-
from __future__ import annotations

from abc import ABC, abstractmethod

from .candidate_base import CandidateExtractionContext
from ..types import ExtractionSnapshot


class TreeExtractor(ABC):
	@abstractmethod
	def supports(self, context: CandidateExtractionContext) -> bool:
		raise NotImplementedError

	@abstractmethod
	def extract(self, context: CandidateExtractionContext) -> ExtractionSnapshot | None:
		raise NotImplementedError
