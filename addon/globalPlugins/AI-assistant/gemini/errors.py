# -*- coding: utf-8 -*-
"""Exceptions raised by the dependency-free Gemini client."""

from typing import Any


class GeminiClientError(RuntimeError):
    """Base exception for Gemini client errors."""

    def __init__(self, message: str, *, details: Any = None) -> None:
        super().__init__(message)
        self.details = details


class GeminiAPIError(GeminiClientError):
    """Raised when Gemini returns an HTTP error or invalid JSON."""

    def __init__(
        self,
        status_code: int,
        body: str,
        error: Any = None,
    ) -> None:
        message = f"Gemini API request failed with status {status_code}."
        super().__init__(message, details=error or body)
        self.status_code = status_code
        self.body = body
        self.error = error
