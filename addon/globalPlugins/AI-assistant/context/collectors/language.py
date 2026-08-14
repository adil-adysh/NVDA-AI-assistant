# -*- coding: utf-8 -*-
from __future__ import annotations

from ...config.settings import get_effective_language
from ..protocols import CollectorInput, ContextFragment
from ..types import ContentRequest


class LanguageContextCollector:
	"""Language metadata collector — always runs for every request."""

	always_collect = True

	def handles_request(self, _request: ContentRequest) -> bool:
		return True

	def collect_for_request(self, _request: ContentRequest, _input_: CollectorInput) -> ContextFragment:
		language = get_effective_language()
		return ContextFragment(
			facts={"language": language},
			metadata={"language": language},
		)
