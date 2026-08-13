# -*- coding: utf-8 -*-
"""Conversation services with lazy compatibility exports.

Leaf modules such as ``chat.types`` must be importable without importing the
conversation coordinator, which depends on the LLM service.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS: dict[str, tuple[str, str]] = {
	"ChatCoordinator": (".coordinator", "ChatCoordinator"),
	"ConversationDeleteResult": (".conversation_service", "ConversationDeleteResult"),
	"ConversationService": (".conversation_service", "ConversationService"),
	"ConversationSummary": (".repository", "ConversationSummary"),
	"ConversationSession": (".session", "ConversationSession"),
	"ChatTurnTransaction": (".transaction", "ChatTurnTransaction"),
	"ConversationTurnResult": (".types", "ConversationTurnResult"),
	"build_default_conversation_repository": (".repository_backends", "build_default_conversation_repository"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
	try:
		module_name, attribute_name = _EXPORTS[name]
	except KeyError as exc:
		raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
	value = getattr(import_module(module_name, __name__), attribute_name)
	globals()[name] = value
	return value
