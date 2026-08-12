# -*- coding: utf-8 -*-
from __future__ import annotations

import builtins
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from ..providers.error_mapping import (
	ErrorSuggestion,
	suggest_for_status,
)
from ..providers.interfaces import (
	FeatureNotSupportedError,
	LLMProviderError,
	ProviderConfigurationError,
	UnsupportedModelError,
)


def _translate(message: str) -> str:
	return message


Translator = Callable[[str], str]
_ = cast(Translator, getattr(builtins, "_", _translate))


@dataclass(frozen=True, slots=True)
class ErrorPresentation:
	title: str
	message: str
	is_internal: bool = False


def _make_presentation(_title: str, suggestion: ErrorSuggestion, translate: Translator) -> ErrorPresentation:
	"""Build an ``ErrorPresentation`` from an ``ErrorSuggestion``."""
	return ErrorPresentation(
		title=translate(suggestion.summary),
		message=translate(suggestion.detail),
		is_internal=not suggestion.actionable,
	)


def _is_connection_refused(message: str) -> bool:
	"""Detect connection-refused / server-not-running errors from the error message."""
	lowered = message.lower()
	# OS-level connection refused patterns (cross-platform).
	if "connection refused" in lowered:
		return True
	if "actively refused" in lowered:
		return True
	if "connect error" in lowered:
		return True
	if "cannot assign requested address" in lowered:
		return True
	return False


def present_error(error: Exception, translate: Translator | None = None) -> ErrorPresentation:
	translate = translate or _
	message_text = str(error).strip()

	# ── User-actionable screen state (e.g. screen curtain active) ──
	from ..image.screen_curtain import ScreenCurtainError

	if isinstance(error, ScreenCurtainError):
		return ErrorPresentation(
			# TRANSLATORS: Title shown when a screen-based feature is blocked by the screen curtain.
			title=translate("Screen curtain active"),
			# The ScreenCurtainError message is already user-facing and actionable.
			message=message_text or translate("Screen capture is unavailable."),
		)

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

	# ── Feature not supported by the active provider (e.g. image description on a text-only model) ──
	if isinstance(error, FeatureNotSupportedError):
		return ErrorPresentation(
			# TRANSLATORS: Title shown when the active provider does not support the requested feature.
			title=translate("Feature not supported"),
			# TRANSLATORS: Message shown when the active provider lacks a capability required by the requested operation.
			message=message_text or translate("The active provider does not support this feature."),
		)

	# ── Generic LLM provider error ──
	if isinstance(error, LLMProviderError):
		# Try to find a status code on the error object for a better suggestion.
		status_code = getattr(error, "status_code", None)
		if isinstance(status_code, int):
			suggestion = suggest_for_status(status_code, fallback_detail=message_text or None)
		elif _is_connection_refused(message_text):
			suggestion = ErrorSuggestion(
				# TRANSLATORS: Summary shown when the local AI model server is unreachable.
				summary=translate("Local server not reachable"),
				# TRANSLATORS: Detail shown when the local AI inference server is not running.
				detail=translate(
					"The local AI inference server could not be reached. "
					"Please verify the server is running and the port is correct "
					"in your provider settings."
				),
			)
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
