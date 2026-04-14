# -*- coding: utf-8 -*-
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ConfigStore(ABC):
	"""Abstract storage interface for AI assistant settings."""

	@abstractmethod
	def load(self) -> None:
		raise NotImplementedError

	@abstractmethod
	def save(self) -> None:
		raise NotImplementedError

	@abstractmethod
	def get(self, key: str, default: Any) -> Any:
		raise NotImplementedError

	@abstractmethod
	def set(self, key: str, value: Any) -> None:
		raise NotImplementedError

	@abstractmethod
	def set_many(self, values: dict[str, Any]) -> None:
		raise NotImplementedError
