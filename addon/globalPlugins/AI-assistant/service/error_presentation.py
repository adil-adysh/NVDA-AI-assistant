# -*- coding: utf-8 -*-
from __future__ import annotations

import builtins
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from ..providers.error_mapping import (
	ErrorSuggestion,
	suggest_for_status,
)
from ..providers.interfaces import LLMProviderError, ProviderConfigurationError, UnsupportedModelError

# ── Provider error mappers (optional — not all providers may be installed) ──

_GeminiAPIError: type | None = None
_map_gemini_error: Any = None
try:
	from ..gemini.errors import GeminiAPIError as _GeminiAPIE
	from ..gemini.error_mapping import map_gemini_error as _map_gemini

	_GeminiAPIError = _GeminiAPIE
	_map_gemini_error = _map_gemini
except ImportError:
	pass

_OpenAIClientError: type | None = None
_map_openai_error: Any = None
try:
	from ..openai.errors import OpenAIClientError as _OpenAIClientE
	from ..openai.error_mapping import map_openai_error as _map_openai

	_OpenAIClientError = _OpenAIClientE
	_map_openai_error = _map_openai
except ImportError:
	pass

_OllamaClientError: type | None = None
_map_ollama_error: Any = None
try:
	from ..ollama.errors import OllamaClientError as _OllamaClientE
	from ..ollama.error_mapping import map_ollama_error as _map_ollama

	_OllamaClientError = _OllamaClientE
	_map_ollama_error = _map_ollama
except ImportError:
	pass


def _translate(message: str) -> str:
	return message


Translator = Callable[[str], str]
_ = cast(Translator, getattr(builtins, "_", _translate))


@dataclass(frozen=True, slots=True)
class ErrorPresentation:
	title: str
	message: str
	is_internal: bool = False


def _make_presentation(title: str, suggestion: ErrorSuggestion, translate: Translator) -> ErrorPresentation:
	"""Build an ``ErrorPresentation`` from an ``ErrorSuggestion``."""
	return ErrorPresentation(
		title=translate(suggestion.summary),
		message=translate(suggestion.detail),
		is_internal=not suggestion.actionable,
	)


def present_error(error: Exception, translate: Translator | None = None) -> ErrorPresentation:
	translate = translate or _
	message_text = str(error).strip()

	# ── Known framework errors (highest priority) ──
	if isinstance(error, UnsupportedModelError):
		return ErrorPresentation(
			# TRANSLATORS: Title shown when the selected AI model is not supported.
			title=translate("Unsupported model"),
			# TRANSLATORS: Message shown when the selected model cannot be used for the current workflow.
			message=message_text or translate("The selected model is not supported for this workflow."),
		)
	if isinstance(error, ProviderConfigurationError):
		return ErrorPresentation(
			# TRANSLATORS: Title shown when the provider configuration is incorrect.
			title=translate("Provider configuration problem"),
			# TRANSLATORS: Message shown when the selected provider is not set up correctly.
			message=message_text or translate("The selected provider is not configured correctly."),
		)

	# ── Gemini API errors ──
	if _GeminiAPIError is not None and isinstance(error, _GeminiAPIError):
		suggestion = _map_gemini_error(error.status_code, error.body)
		# TRANSLATORS: Title shown when a Gemini API request fails.
		return _make_presentation(translate("Gemini request failed"), suggestion, translate)

	# ── OpenAI API errors ──
	if _OpenAIClientError is not None and isinstance(error, _OpenAIClientError):
		suggestion = _map_openai_error(
			getattr(error, "status_code", None),
			message_text or None,
			body=None,
		)
		# TRANSLATORS: Title shown when an OpenAI API request fails.
		return _make_presentation(translate("OpenAI request failed"), suggestion, translate)

	# ── Ollama errors ──
	if _OllamaClientError is not None and isinstance(error, _OllamaClientError):
		suggestion = _map_ollama_error(
			status_code=None,
			body=None,
			message=message_text or None,
		)
		# TRANSLATORS: Title shown when an Ollama request fails.
		return _make_presentation(translate("Ollama request failed"), suggestion, translate)

	# ── Generic LLM provider error ──
	if isinstance(error, LLMProviderError):
		# Try to find a status code on the error object for a better suggestion.
		status_code = getattr(error, "status_code", None)
		if isinstance(status_code, int):
			suggestion = suggest_for_status(status_code, fallback_detail=message_text or None)
		else:
			suggestion = ErrorSuggestion(
				# TRANSLATORS: Summary shown when a provider request fails without a specific error code.
				summary=translate("Provider request failed"),
				detail=message_text or translate("The selected provider could not complete the request."),
			)
		# TRANSLATORS: Title shown when a provider request fails.
		return _make_presentation(translate("Provider request failed"), suggestion, translate)

	# ── Fallback — unexpected internal error ──
	return ErrorPresentation(
		# TRANSLATORS: Title shown when an unexpected internal error occurs in the add-on.
		title=translate("Internal error"),
		# TRANSLATORS: Message shown when an unexpected internal error occurs, asking the user to try again.
		message=translate("Something went wrong inside the add-on. Please try again."),
		is_internal=True,
	)
