"""Single boundary for converting failures into user-visible notifications."""
from __future__ import annotations

import builtins
from collections.abc import Callable
from dataclasses import dataclass
import threading
import uuid

import logging

from .error_presentation import ErrorPresentation, Translator, present_error

log = logging.getLogger(__name__)

try:
	_ = builtins._
except AttributeError:
	def _(text: str) -> str:
		return text


@dataclass(frozen=True, slots=True)
class ErrorContext:
	operation: str
	provider: str | None = None
	model: str | None = None
	origin: str | None = None
	optional: bool = False


ErrorSurface = Callable[[ErrorPresentation], None]


class ErrorReporter:
	"""Report errors to a contextual surface, or NVDA as a safe fallback."""

	def __init__(self, notify: Callable[[str], None] | None = None) -> None:
		self._notify = notify or self._default_notify
		self._seen: set[tuple[str, str]] = set()
		self._lock = threading.Lock()

	@staticmethod
	def _default_notify(message: str) -> None:
		try:
			from ..ui import nvda_ui

			nvda_ui.queue(nvda_ui.message, message)
		except Exception:
			# Reporting must never become a second failure in a worker thread.
			log.exception("Unable to deliver global AI Assistant error notification")

	@staticmethod
	def _diagnostic_id() -> str:
		return uuid.uuid4().hex[:10]

	def report(
		self,
		error: Exception,
		context: ErrorContext,
		owner: ErrorSurface | None = None,
		*,
		translate: Translator | None = None,
	) -> ErrorPresentation:
		diagnostic_id = self._diagnostic_id()
		log.error(
			"User-visible operation failed [%s] operation=%s provider=%s model=%s origin=%s: %s",
			diagnostic_id,
			context.operation,
			context.provider,
			context.model,
			context.origin,
			error,
			exc_info=True,
		)
		presentation = present_error(error, translate, diagnostic_id)
		if context.optional:
			key = (context.operation, str(error))
			with self._lock:
				if key in self._seen:
					return presentation
				self._seen.add(key)
		if owner is not None:
			try:
				owner(presentation)
				return presentation
			except Exception:
				log.exception("Contextual error surface failed for %s", context.operation)
		message = f"{presentation.title}: {presentation.message}"
		self._notify(message)
		return presentation


error_reporter = ErrorReporter()


__all__ = ["ErrorContext", "ErrorReporter", "ErrorSurface", "error_reporter"]
