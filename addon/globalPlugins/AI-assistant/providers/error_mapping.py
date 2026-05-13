# -*- coding: utf-8 -*-
"""Generic HTTP / gRPC status code to user-friendly error message mapping.

This is the foundation layer for provider error presentation.  It maps
standard HTTP status codes and Google ``google.rpc.Code`` values to
user-facing messages that are actionable.

Layer rules
-----------
- This module MUST NOT import from any provider-specific package
  (gemini/, openai/, ollama/).  It only knows about HTTP semantics.
- Provider-specific error parsing lives in each provider's ``error_mapping.py``.
- The orchestrator in ``service/error_presentation.py`` imports from both
  this module and provider-specific mappers.
"""
from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Canonical error code registry
# ---------------------------------------------------------------------------

# Google ``google.rpc.Code`` values commonly returned by Gemini and
# OpenAI-compatible APIs, mapped to HTTP status codes.

HTTP_RPC_MAP: dict[int, str] = {
	400: "INVALID_ARGUMENT",
	401: "UNAUTHENTICATED",
	403: "PERMISSION_DENIED",
	404: "NOT_FOUND",
	409: "ABORTED",
	429: "RESOURCE_EXHAUSTED",
	499: "CANCELLED",
	500: "INTERNAL",
	503: "UNAVAILABLE",
	504: "DEADLINE_EXCEEDED",
}


@dataclass(frozen=True, slots=True)
class ErrorSuggestion:
	"""A user-facing error message and optional recovery hint."""

	summary: str
	detail: str
	actionable: bool = True


# ---------------------------------------------------------------------------
# HTTP status code → user-friendly suggestion
# ---------------------------------------------------------------------------

_STATUS_SUGGESTIONS: dict[int, ErrorSuggestion] = {
	400: ErrorSuggestion(
		summary="Invalid request",
		detail="The request was malformed or contains invalid parameters. Check the message format and try again.",
		actionable=True,
	),
	401: ErrorSuggestion(
		summary="Authentication failed",
		detail="The API key is missing or invalid. Check your provider settings and ensure the key is correct.",
		actionable=True,
	),
	403: ErrorSuggestion(
		summary="Access denied",
		detail="The API key does not have permission for this operation. Check your API key permissions or billing status.",
		actionable=False,
	),
	404: ErrorSuggestion(
		summary="Resource not found",
		detail="The requested model or resource was not found. Verify the model name and API endpoint.",
		actionable=True,
	),
	409: ErrorSuggestion(
		summary="Request conflict",
		detail="The request conflicted with the current state of the resource. Please try again.",
		actionable=True,
	),
	429: ErrorSuggestion(
		summary="Rate limit exceeded",
		detail="Too many requests. Wait a moment before sending another message, or consider upgrading your plan.",
		actionable=True,
	),
	499: ErrorSuggestion(
		summary="Request cancelled",
		detail="The request was cancelled before completion.",
		actionable=True,
	),
	500: ErrorSuggestion(
		summary="Server error",
		detail="The AI provider encountered an internal error. This is usually temporary — try again in a few moments.",
		actionable=True,
	),
	503: ErrorSuggestion(
		summary="Service unavailable",
		detail="The AI provider is temporarily overloaded or undergoing maintenance. Try again later or switch to a different model.",
		actionable=True,
	),
	504: ErrorSuggestion(
		summary="Request timed out",
		detail="The request took too long to complete. Try a shorter message or a different model.",
		actionable=True,
	),
}


def suggest_for_status(status_code: int | None, fallback_detail: str | None = None) -> ErrorSuggestion:
	"""Return a user-friendly ``ErrorSuggestion`` for an HTTP status code.

	Parameters
	----------
	status_code:
		The HTTP status code (or ``None`` if unknown).
	fallback_detail:
		Optional original error detail to include when the status code
		is not in the registry.

	Returns
	-------
	ErrorSuggestion
		A suggestion with ``summary``, ``detail``, and ``actionable`` fields.
	"""
	if status_code is not None and status_code in _STATUS_SUGGESTIONS:
		return _STATUS_SUGGESTIONS[status_code]
	# Provide a sensible fallback for unknown codes.
	code_name = HTTP_RPC_MAP.get(status_code) if status_code else "UNKNOWN"
	detail = fallback_detail or f"The provider returned an unexpected response (HTTP {status_code} / {code_name})."
	return ErrorSuggestion(
		summary="Provider request failed",
		detail=detail,
		actionable=True,
	)


# ---------------------------------------------------------------------------
# Generic provider-agnostic error message extraction
# ---------------------------------------------------------------------------


def extract_error_message(error: Exception) -> str | None:
	"""Extract a human-readable message from an arbitrary exception.

	Handles common exception types generically.  Provider-specific
	extraction (Gemini, OpenAI, Ollama) is done in each provider's
	``error_mapping.py``.
	"""
	message = str(error).strip()
	if message:
		return message
	return None
