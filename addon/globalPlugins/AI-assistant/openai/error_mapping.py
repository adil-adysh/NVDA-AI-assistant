# -*- coding: utf-8 -*-
"""OpenAI API-specific error mapping.

OpenAI uses standard HTTP status codes with a JSON error body::

    {
      "error": {
        "message": "...",
        "type": "invalid_request_error",
        "param": null,
        "code": "rate_limit_exceeded"
      }
    }
"""
from __future__ import annotations

from ..providers.error_mapping import ErrorSuggestion, suggest_for_status


# OpenAI-specific error code overrides
_OPENAI_ERROR_CODES: dict[str, ErrorSuggestion] = {
	"rate_limit_exceeded": ErrorSuggestion(
		summary="Rate limit exceeded",
		detail="Too many requests. Wait a moment before sending another message, or check your OpenAI usage tier.",
		actionable=True,
	),
	"insufficient_quota": ErrorSuggestion(
		summary="Quota exceeded",
		detail="You've used up your OpenAI API quota. Check your billing and usage in the OpenAI dashboard.",
		actionable=True,
	),
	"invalid_api_key": ErrorSuggestion(
		summary="Invalid API key",
		detail="The OpenAI API key is invalid. Check your key in the provider settings.",
		actionable=True,
	),
	"model_not_found": ErrorSuggestion(
		summary="Model not found",
		detail="The requested OpenAI model is not available. Check the model name and your API access level.",
		actionable=True,
	),
	"context_length_exceeded": ErrorSuggestion(
		summary="Message too long",
		detail="The conversation is too long for the selected model. Start a new conversation or reduce the message length.",
		actionable=True,
	),
}


def map_openai_error(status_code: int | None, message: str | None, body: str | None = None) -> ErrorSuggestion:
	"""Map an OpenAI API error to a user-friendly ``ErrorSuggestion``."""
	# Try to extract a structured error code from the body.
	error_code: str | None = None
	error_message: str | None = None
	if body:
		try:
			import json
			payload = json.loads(body)
			if isinstance(payload, dict):
				error_obj = payload.get("error")
				if isinstance(error_obj, dict):
					error_code = error_obj.get("code")
					error_message = error_obj.get("message") or error_message
		except (ValueError, TypeError):
			pass

	# Look up known error codes.
	if isinstance(error_code, str) and error_code in _OPENAI_ERROR_CODES:
		suggestion = _OPENAI_ERROR_CODES[error_code]
		if error_message and error_message not in suggestion.detail:
			object.__setattr__(suggestion, "detail", f"{suggestion.detail}\n\n{error_message}")
		return suggestion

	# Fall through to the generic HTTP mapper.
	detail = error_message or message or None
	return suggest_for_status(status_code, fallback_detail=detail)
