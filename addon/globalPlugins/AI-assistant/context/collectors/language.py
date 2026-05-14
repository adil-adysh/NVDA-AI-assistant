# -*- coding: utf-8 -*-
from __future__ import annotations

from ...config.settings import get_effective_language
from ..protocols import CollectorInput, ContextFragment
from ..types import ContentRequest


class LanguageContextCollector:
	def handles_request(self, _request: ContentRequest) -> bool:
		"""Language metadata is always collected — it is not request-specific."""
		return True

	def collect_for_request(self, _request: ContentRequest, input: CollectorInput) -> ContextFragment:
		language = get_effective_language()
		return ContextFragment(
			facts={"language": language},
			metadata={"language": language},
		)
