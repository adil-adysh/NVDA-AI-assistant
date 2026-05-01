# -*- coding: utf-8 -*-
from __future__ import annotations


class OpenAIClientError(RuntimeError):
    """Raised for OpenAI client request or response failures."""

    def __init__(self, message: str, *, status_code: int | None = None, path: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.path = path


class OpenAIClientConfigurationError(OpenAIClientError):
    """Raised when the OpenAI client is configured incorrectly."""
