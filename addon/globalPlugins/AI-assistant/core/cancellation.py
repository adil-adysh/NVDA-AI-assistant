"""Cooperative, request-scoped cancellation without changing shared providers."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Callable
import threading


class RequestCancelled(Exception):
	def __init__(self, partial_text: str = '') -> None:
		super().__init__('Request stopped')
		self.partial_text = partial_text


class CancellationToken:
	def __init__(self) -> None:
		self._event = threading.Event()
		self.partial_text = ''
		self._acquire_delivery: Callable[[], None] | None = None
		self._release_delivery: Callable[[], None] | None = None

	def bind_delivery_lifetime(self, acquire: Callable[[], None], release: Callable[[], None]) -> None:
		"""Let a request owner track presentation that outlives its worker."""
		self._acquire_delivery = acquire
		self._release_delivery = release

	def hold_delivery(self) -> Callable[[], None]:
		if self._acquire_delivery is None or self._release_delivery is None:
			return lambda: None
		self._acquire_delivery()
		released = False
		lock = threading.Lock()
		def release_once() -> None:
			nonlocal released
			with lock:
				if released:
					return
				released = True
			self._release_delivery()
		return release_once

	@property
	def cancelled(self) -> bool:
		return self._event.is_set()

	def cancel(self) -> None:
		self._event.set()


_current_token: ContextVar[CancellationToken | None] = ContextVar('inference_cancellation', default=None)


@contextmanager
def cancellation_scope(token: CancellationToken | None):
	if token is None:
		yield
		return
	marker = _current_token.set(token)
	try:
		yield
	finally:
		_current_token.reset(marker)


def current_cancellation_token() -> CancellationToken | None:
	return _current_token.get()


def check_cancelled() -> None:
	token = _current_token.get()
	if token is not None and token.cancelled:
		raise RequestCancelled(token.partial_text)


def record_partial(text: str, generated_chars: int) -> None:
	check_cancelled()
	token = _current_token.get()
	if token is not None:
		# Most adapters report accumulated text; delta callbacks report a total
		# generated character count larger than the current chunk.
		if generated_chars > len(text) and generated_chars >= len(token.partial_text) + len(text):
			token.partial_text += text
		else:
			token.partial_text = text
