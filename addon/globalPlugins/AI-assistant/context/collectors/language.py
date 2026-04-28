# -*- coding: utf-8 -*-
from __future__ import annotations

from ...config.settings import get_effective_language
from ..protocols import CollectorInput, ContextCollector, ContextFragment
from ..types import APP, IMAGE, PAGE


class LanguageContextCollector:
	@property
	def profiles(self) -> tuple[str, ...]:
		return (APP, PAGE, IMAGE)

	def collect(self, input: CollectorInput) -> ContextFragment:
		language = get_effective_language()
		return ContextFragment(
			facts={"language": language},
			metadata={"language": language},
		)
