# -*- coding: utf-8 -*-
from __future__ import annotations

from abc import ABC, abstractmethod

from .candidate_base import CandidateExtractionContext
from ..types import ExtractionSnapshot


class Extractor(ABC):
	@abstractmethod
	def supports(self, context: CandidateExtractionContext) -> bool:
		raise NotImplementedError

	@abstractmethod
	def extract(self, context: CandidateExtractionContext) -> ExtractionSnapshot | None:
		raise NotImplementedError


class TreeExtractor(Extractor):
	"""Extractor specialized for tree-like candidate content."""
