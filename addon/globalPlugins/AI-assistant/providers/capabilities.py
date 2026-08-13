# -*- coding: utf-8 -*-
"""Provider-independent model capability value objects and ports.

Capability inspection is deliberately expressed as a small port.  Providers
may obtain metadata from an API, a local model manifest, or a future llama.cpp
backend without making the application layer know how inspection works.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from typing import Protocol


CAPABILITY_CHAT = "chat"
CAPABILITY_COMPLETION = "completion"
CAPABILITY_IMAGE_INPUT = "image_input"
CAPABILITY_STREAMING = "streaming"
CAPABILITY_TEXT_INPUT = "text_input"
CAPABILITY_TEXT_OUTPUT = "text_output"
CAPABILITY_THINKING = "thinking"
CAPABILITY_TOOLS = "tools"


@dataclass(frozen=True)
class ModelCapabilities:
	"""Immutable, normalized capabilities for one provider model."""

	values: frozenset[str] = frozenset()

	def supports(self, capability: str) -> bool:
		return capability.strip().lower() in self.values

	@classmethod
	def from_iterable(cls, values: object) -> "ModelCapabilities":
		if not isinstance(values, (list, tuple, set, frozenset)):
			return cls()
		normalized = frozenset(str(value).strip().lower() for value in values if str(value).strip())
		return cls(normalized)


class CapabilityInspector(Protocol):
	"""Port for resolving capabilities without exposing provider mechanics."""

	def inspect(self, model_id: str) -> ModelCapabilities: ...


class CachedCapabilityInspector:
	"""Thread-safe per-model cache around any capability inspector.

	The cache is intentionally provider-instance scoped.  A provider's endpoint,
	credentials, and model catalog define the inspection context, so sharing
	entries globally would risk returning metadata from a different endpoint.
	"""

	def __init__(self, loader: Callable[[str], ModelCapabilities]) -> None:
		self._loader = loader
		self._lock = RLock()
		self._values: dict[str, ModelCapabilities] = {}

	def inspect(self, model_id: str) -> ModelCapabilities:
		key = model_id.strip()
		with self._lock:
			cached = self._values.get(key)
		if cached is not None:
			return cached
		value = self._loader(key)
		with self._lock:
			# setdefault also handles two simultaneous first inspections safely.
			return self._values.setdefault(key, value)

	def invalidate(self, model_id: str | None = None) -> None:
		with self._lock:
			if model_id is None:
				self._values.clear()
			else:
				self._values.pop(model_id.strip(), None)

	def __len__(self) -> int:
		with self._lock:
			return len(self._values)
