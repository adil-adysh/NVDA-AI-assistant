# -*- coding: utf-8 -*-
"""Declarative metadata for context request capabilities."""
from __future__ import annotations

from dataclasses import dataclass

from .types import ContextCollectionError


@dataclass(frozen=True, slots=True)
class ContextRequestDefinition:
	kind: str
	resolver: str | None = None
	image_source: str | None = None


DEFAULT_CONTEXT_REQUESTS: dict[str, ContextRequestDefinition] = {
	"page_text": ContextRequestDefinition("page_text", resolver="page"),
	"page_structure": ContextRequestDefinition("page_structure", resolver="page"),
	"focused_text": ContextRequestDefinition("focused_text", resolver="focused_text"),
	"foreground_image": ContextRequestDefinition("foreground_image", resolver="image", image_source="foreground"),
	"focused_element_image": ContextRequestDefinition("focused_element_image", resolver="image", image_source="focus"),
	"navigator_image": ContextRequestDefinition("navigator_image", resolver="image", image_source="navigator"),
}


class ContextRequestRegistry:
	"""Validated registry of context capabilities available to use cases."""

	def __init__(self, definitions: tuple[ContextRequestDefinition, ...] | None = None) -> None:
		self._definitions: dict[str, ContextRequestDefinition] = dict(DEFAULT_CONTEXT_REQUESTS)
		for definition in definitions or ():
			self.register(definition)

	def register(self, definition: ContextRequestDefinition) -> None:
		if definition.kind in self._definitions:
			raise ValueError(f"Context request kind already registered: {definition.kind}")
		self._definitions[definition.kind] = definition

	def get(self, kind: str) -> ContextRequestDefinition:
		try:
			return self._definitions[kind]
		except KeyError as error:
			raise ContextCollectionError(f"Unknown context request kind: {kind}") from error

	def validate(self, kinds: tuple[str, ...]) -> None:
		for kind in kinds:
			self.get(kind)
