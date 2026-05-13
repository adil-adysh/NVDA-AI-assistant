# -*- coding: utf-8 -*-
"""Ollama-specific error mapping.

Ollama returns HTTP errors with a plain-text or JSON body containing
an ``error`` field::

    {"error": "model \"xyz\" not found, try pulling it first"}
"""
from __future__ import annotations

from ..providers.error_mapping import ErrorSuggestion, suggest_for_status


# Ollama-specific error code overrides
_OLLAMA_STATUS_OVERRIDES: dict[int, ErrorSuggestion] = {
	404: ErrorSuggestion(
		summary="Model not available",
		detail="The requested model was not found locally. Use the model pull feature to download it first.",
		actionable=True,
	),
}


def map_ollama_error(status_code: int | None, body: str | None, message: str | None = None) -> ErrorSuggestion:
	"""Map an Ollama error to a user-friendly ``ErrorSuggestion``."""
	# Try to extract "error" field from JSON body.
	error_message: str | None = None
	if body:
		try:
			import json
			payload = json.loads(body)
			if isinstance(payload, dict):
				err_text = payload.get("error")
				if isinstance(err_text, str) and err_text.strip():
					error_message = err_text.strip()
		except (ValueError, TypeError):
			pass

	# Model not found locally — common Ollama case.
	if error_message and any(kw in (error_message or "").lower() for kw in ("not found", "pull it first")):
		return _OLLAMA_STATUS_OVERRIDES.get(404, suggest_for_status(404))

	# Check for status-specific override.
	if status_code in _OLLAMA_STATUS_OVERRIDES:
		return _OLLAMA_STATUS_OVERRIDES[status_code]

	# Fall through to generic HTTP mapper.
	detail = (error_message or message or "").strip() or None
	return suggest_for_status(status_code, fallback_detail=detail)
