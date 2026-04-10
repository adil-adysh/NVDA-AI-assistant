# -*- coding: utf-8 -*-
"""Minimal dependency-free Gemini client for NVDA AI Assistant."""

from .client import GeminiClient, ChatSession, Chats
from .errors import GeminiAPIError, GeminiClientError
from .types import (
    Candidate,
    Content,
    GenerateContentConfig,
    GenerateContentResponse,
    Part,
    SafetySetting,
)

__all__ = [
    "GeminiClient",
    "GeminiAPIError",
    "GeminiClientError",
    "Candidate",
    "Content",
    "GenerateContentConfig",
    "GenerateContentResponse",
    "Part",
    "SafetySetting",
    "ChatSession",
    "Chats",
]
