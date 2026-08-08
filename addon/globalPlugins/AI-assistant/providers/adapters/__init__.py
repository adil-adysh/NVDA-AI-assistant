# -*- coding: utf-8 -*-
from __future__ import annotations

from .openai_compat import OpenAICompatProvider

# Backward-compatibility aliases
GeminiProvider = OpenAICompatProvider
LiteRTLMProvider = OpenAICompatProvider
OllamaProvider = OpenAICompatProvider
OpenAIProvider = OpenAICompatProvider

__all__ = [
    "GeminiProvider",
    "LiteRTLMProvider",
    "OllamaProvider",
    "OpenAIProvider",
    "OpenAICompatProvider",
]
