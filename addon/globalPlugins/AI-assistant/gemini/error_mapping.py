# -*- coding: utf-8 -*-
"""Gemini API-specific error body parsing and user-friendly message mapping.

This module understands the Gemini API error response format and produces
actionable user-facing messages by delegating HTTP status codes to the
generic ``providers/error_mapping.py`` mapper.

Gemini error response format (JSON)::

    {
      "error": {
        "code": 400,
        "message": "...",
        "status": "INVALID_ARGUMENT",
        "details": [...]
      }
    }
"""
from __future__ import annotations

from typing import Any

from ..providers.error_mapping import (
	ErrorSuggestion,
	suggest_for_status,
)


# ---------------------------------------------------------------------------
# Gemini-specific status code qualifiers
# ---------------------------------------------------------------------------

# Some Gemini error codes have a different user-facing meaning than
# the generic HTTP mapping.  Override them here.
_GEMINI_STATUS_OVERRIDES: dict[int, ErrorSuggestion] = {
	400: ErrorSuggestion(
		summary="Invalid request",
		detail="The request was malformed. Check for typos, missing fields, or unsupported parameter values.",
		actionable=True,
	),
	404: ErrorSuggestion(
		summary="Resource not found",
		detail="The requested model or file was not found. Verify the model name is correct and the file URI is valid.",
		actionable=True,
	),
}


# ---------------------------------------------------------------------------
# Gemini "status" string → user-friendly message
# ---------------------------------------------------------------------------

_GEMINI_STATUS_MESSAGES: dict[str, str] = {
	"INVALID_ARGUMENT": "One or more request parameters are invalid. Check the message format and try again.",
	"FAILED_PRECONDITION": (
		"The Gemini API free tier is unavailable in your region. "
		"Set up a paid plan in Google AI Studio to continue using this service."
	),
	"PERMISSION_DENIED": "Your API key does not have permission for this operation. Check API key permissions and billing.",
	"UNAUTHENTICATED": "The API key is missing or invalid. Check your Gemini API key in the provider settings.",
	"NOT_FOUND": "The requested model or resource was not found. Verify the model name and try again.",
	"RESOURCE_EXHAUSTED": "You've exceeded the rate limit. Wait a moment before sending another message.",
	"DEADLINE_EXCEEDED": "The request timed out. Try a shorter message or a different model.",
	"ABORTED": "The operation was aborted. Please try again.",
	"CANCELLED": "The request was cancelled.",
	"INTERNAL": "Gemini encountered an internal error. Check the service status page and try again.",
	"UNAVAILABLE": "Gemini is temporarily overloaded. Try again later or switch to a different model.",
}


def _parse_gemini_error_body(body: str) -> dict[str, Any] | None:
	"""Try to parse a Gemini API error body as JSON.

	Returns the ``error`` dict (or the whole payload if no nested ``error`` key),
	or ``None`` if the body is not valid JSON.
	"""
	try:
		import json
		payload = json.loads(body)
		if isinstance(payload, dict):
			error_obj = payload.get("error")
			if isinstance(error_obj, dict):
				return error_obj
			return payload
	except (ValueError, TypeError):
		pass
	return None


def map_gemini_error(status_code: int, body: str) -> ErrorSuggestion:
	"""Map a Gemini API error to a user-friendly ``ErrorSuggestion``.

	Parameters
	----------
	status_code: HTTP status code returned by the Gemini API.
	body: Raw response body (should be JSON, but may be plain text).

	Returns
	-------
	ErrorSuggestion with ``summary``, ``detail``, and ``actionable`` fields.
	"""
	# Try structured JSON body first.
	error_obj = _parse_gemini_error_body(body)
	if error_obj is not None:
		status_str = error_obj.get("status", "")
		message = error_obj.get("message", "")
		if isinstance(status_str, str) and status_str in _GEMINI_STATUS_MESSAGES:
			detail = _GEMINI_STATUS_MESSAGES[status_str]
			if message and message not in detail:
				detail = f"{detail}\n\n{message}"
			# Map FAILED_PRECONDITION (HTTP 400) specifically.
			if status_str == "FAILED_PRECONDITION":
				return ErrorSuggestion(
					summary="Billing required",
					detail=detail,
					actionable=True,
				)
			return ErrorSuggestion(
				summary="Gemini request failed",
				detail=detail,
				actionable=True,
			)
		# Fall back to the message field if we have one.
		if isinstance(message, str) and message.strip():
			return ErrorSuggestion(
				summary="Gemini request failed",
				detail=message.strip(),
				actionable=True,
			)

	# Check for gemini-specific status override.
	if status_code in _GEMINI_STATUS_OVERRIDES:
		return _GEMINI_STATUS_OVERRIDES[status_code]

	# Fall through to the generic HTTP mapper.
	return suggest_for_status(status_code, fallback_detail=body.strip() or None)
