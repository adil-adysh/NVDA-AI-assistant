# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
from collections.abc import Sequence

from .base import TreeExtractor
from .browser import PageExtractionError
from .candidate_base import CandidateExtractionContext
from .context_builder import build_extraction_context

log = logging.getLogger(__name__)


class ExtractionManager(TreeExtractor):
	def __init__(self, extractors: Sequence[TreeExtractor] | None = None):
		self._extractors = tuple(extractors or ())

	def supports(self, context: CandidateExtractionContext) -> bool:
		return any(extractor.supports(context) for extractor in self._extractors)

	def extract(self):
		context = build_extraction_context()
		last_page_extraction_error: PageExtractionError | None = None
		for extractor in self._extractors:
			try:
				if not extractor.supports(context):
					continue
				extraction = extractor.extract()
				if extraction is not None:
					return extraction
			except PageExtractionError as error:
				last_page_extraction_error = error
			except Exception as error:
				log.debug("ExtractionManager: extractor %s failed: %s", type(extractor).__name__, error, exc_info=True)
		if last_page_extraction_error is not None:
			raise last_page_extraction_error
		return None
