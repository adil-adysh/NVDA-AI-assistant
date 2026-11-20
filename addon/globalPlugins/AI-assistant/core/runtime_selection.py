"""Shared launch fence installed by the application, absent in the private worker."""
from __future__ import annotations

from collections.abc import Callable
from functools import wraps
import threading
from typing import ParamSpec, TypeVar

from .cancellation import RequestCancelled

P = ParamSpec("P")
R = TypeVar("R")


class RuntimeSelectionGate:
	def __init__(self, get_provider: Callable[[], str]) -> None:
		self._get_provider = get_provider
		self._lock = threading.RLock()
		self._closed = threading.Event()

	def is_selected(self, provider: str) -> bool:
		return not self._closed.is_set() and self._get_provider() == provider

	def run(self, provider: str, operation: Callable[[], R]) -> R:
		with self._lock:
			if not self.is_selected(provider):
				raise RequestCancelled()
			return operation()

	def close(self) -> None:
		self._closed.set()


_gate: RuntimeSelectionGate | None = None


def set_runtime_selection_gate(gate: RuntimeSelectionGate | None) -> None:
	global _gate
	_gate = gate


def runtime_launch(provider: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
	def decorate(operation: Callable[P, R]) -> Callable[P, R]:
		@wraps(operation)
		def guarded(*args: P.args, **kwargs: P.kwargs) -> R:
			gate = _gate
			if gate is None:
				return operation(*args, **kwargs)
			return gate.run(provider, lambda: operation(*args, **kwargs))
		return guarded
	return decorate
