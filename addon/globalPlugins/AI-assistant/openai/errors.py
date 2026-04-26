# -*- coding: utf-8 -*-
from __future__ import annotations


class OpenAIClientError(RuntimeError):
    """Raised for OpenAI client request or response failures."""


class OpenAIClientConfigurationError(OpenAIClientError):
    """Raised when the OpenAI client is configured incorrectly."""
