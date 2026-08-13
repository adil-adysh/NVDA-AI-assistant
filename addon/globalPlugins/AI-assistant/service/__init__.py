# -*- coding: utf-8 -*-
"""Application services.

The package intentionally exposes lazy compatibility exports.  Importing a
leaf service such as ``service.model_cache`` must not import chat, UI, or
provider runtime modules as a side effect.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS: dict[str, tuple[str, str]] = {
	"ChatCoordinator": (".chat", "ChatCoordinator"),
	"ChatTurnTransaction": (".chat", "ChatTurnTransaction"),
	"ConversationSession": (".chat", "ConversationSession"),
	"ConversationTurnResult": (".chat", "ConversationTurnResult"),
	"LLMService": (".llm", "LLMService"),
	"ModelCapabilityCache": (".model_cache", "ModelCapabilityCache"),
	"ModelCatalogCache": (".model_cache", "ModelCatalogCache"),
	"ModelSwitchResult": (".provider_controls", "ModelSwitchResult"),
	"ProviderLLMService": (".llm", "ProviderLLMService"),
	"ProviderCatalogService": (".provider_catalog", "ProviderCatalogService"),
	"ProviderControlResult": (".provider_controls", "ProviderControlResult"),
	"ProviderControlService": (".provider_controls", "ProviderControlService"),
	"ProviderReadiness": (".provider_readiness", "ProviderReadiness"),
	"ProviderReadinessReason": (".provider_readiness", "ProviderReadinessReason"),
	"ProviderReadinessService": (".provider_readiness", "ProviderReadinessService"),
	"ProviderReadinessState": (".provider_readiness", "ProviderReadinessState"),
	"get_provider_display_name": (".provider_readiness", "get_provider_display_name"),
	"model_capability_cache": (".model_cache", "model_capability_cache"),
	"model_catalog_cache": (".model_cache", "model_catalog_cache"),
	"provider_control_service": (".provider_controls", "provider_control_service"),
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
