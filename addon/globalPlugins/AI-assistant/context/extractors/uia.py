# -*- coding: utf-8 -*-
from __future__ import annotations

from .base import TreeExtractor
from .candidate_base import CandidateExtractionContext
from ..types import ExtractionSnapshot


class UIATreeExtractor(TreeExtractor):
	def supports(self, context: CandidateExtractionContext) -> bool:
		# TODO: implement UIA capability detection when UIA objects are available.
		return False

	def extract(self, context: CandidateExtractionContext) -> ExtractionSnapshot | None:
		return None
