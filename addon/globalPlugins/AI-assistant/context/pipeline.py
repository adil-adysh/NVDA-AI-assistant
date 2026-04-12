# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Sequence

from .protocols import ContextCollector, ContextFragment
from .types import PromptContext


class ContextPipeline:
	def __init__(self, collectors: Sequence[ContextCollector]) -> None:
		self._collectors = tuple(collectors)

	def collect(self, use_case_id: str, context_profile: tuple[str, ...], **kwargs: Any) -> PromptContext:
		merged_facts: dict[str, Any] = {}
		merged_metadata: dict[str, Any] = {"context_profile": context_profile}
		text_parts: list[str] = []
		image_base64: str | None = None

		for collector in self._collectors:
			if not context_profile:
				continue
			if not set(collector.profiles).intersection(context_profile):
				continue
			fragment = collector.collect(use_case_id, **kwargs)
			merged_facts.update(fragment.facts)
			merged_metadata.update(fragment.metadata)
			if fragment.text:
				text_parts.append(fragment.text)
			if fragment.image_base64 is not None:
				image_base64 = fragment.image_base64

		return PromptContext(
			use_case_id=use_case_id,
			facts=merged_facts,
			text="\n\n".join(part for part in text_parts if part),
			image_base64=image_base64,
			metadata=merged_metadata,
		)
