# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .types import ContentSnapshot, ContextProfileList


@dataclass(frozen=True, slots=True)
class ContextFragment:
	facts: dict[str, Any] = field(default_factory=dict)
	text: str | None = None
	image_base64: str | None = None
	metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CollectorInput:
	use_case_id: str
	snapshot: ContentSnapshot | None = None


class ExtractorProtocol(Protocol):
	def extract(self) -> ContentSnapshot | None:
		...


class NVDAContextProvider(Protocol):
	def get_focus_object(self) -> object | None:
		...

	def get_focus_ancestors(self) -> tuple[object, ...]:
		...

	def get_navigator_object(self) -> object | None:
		...

	def get_foreground_object(self) -> object | None:
		...

	def get_tree_interceptor(self, obj: object | None) -> object | None:
		...

	def make_text_info(self, obj: object | None, position: str = "all") -> Any | None:
		...

	def get_app_name(self, obj: object | None) -> str | None:
		...

	def get_object_title(self, obj: object | None) -> str | None:
		...


class ContextCollector(Protocol):
	@property
	def profiles(self) -> ContextProfileList:
		...

	def collect(self, input: CollectorInput) -> ContextFragment:
		...
