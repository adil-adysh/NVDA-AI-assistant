# -*- coding: utf-8 -*-
"""Persisted configuration schemas for registered providers.

This is the configuration adapter boundary: provider implementations do not
read YAML keys, and settings code does not need provider-ID conditionals.
Adding a backend requires registering its schema here and its runtime policy
in ``providers.policy``.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import defaults


@dataclass(frozen=True)
class ProviderConfigSpec:
	provider_id: str
	model_key: str
	model_default: str
	base_url_key: str
	base_url_default: str
	executable_key: str | None = None
	executable_default: str = ""
	models_preset_key: str | None = None
	models_preset_default: str = ""
	api_key_key: str | None = None
	api_token_key: str | None = None
	chat_path_key: str | None = None
	chat_path_default: str = defaults.DEFAULT_OPENAI_CHAT_PATH
	models_path: str = defaults.DEFAULT_OPENAI_MODELS_PATH
	litert_engine_settings: bool = False


PROVIDER_CONFIG_SPECS: dict[str, ProviderConfigSpec] = {
	"ollama": ProviderConfigSpec(
		provider_id="ollama",
		model_key="ollamaModelName",
		model_default=defaults.DEFAULT_OLLAMA_MODEL,
		base_url_key="ollamaServerUrl",
		base_url_default=defaults.DEFAULT_OLLAMA_URL,
	),
	"gemini": ProviderConfigSpec(
		provider_id="gemini",
		model_key="geminiModelName",
		model_default=defaults.DEFAULT_GEMINI_MODEL,
		base_url_key="geminiBaseUrl",
		base_url_default=defaults.DEFAULT_GEMINI_BASE_URL,
		api_key_key="geminiApiKey",
		api_token_key="geminiApiToken",
		chat_path_default=defaults.DEFAULT_GEMINI_CHAT_PATH,
		models_path=defaults.DEFAULT_GEMINI_MODELS_PATH,
	),
	"openai": ProviderConfigSpec(
		provider_id="openai",
		model_key="openaiModelName",
		model_default=defaults.DEFAULT_OPENAI_MODEL,
		base_url_key="openaiBaseUrl",
		base_url_default=defaults.DEFAULT_OPENAI_BASE_URL,
		api_key_key="openaiApiKey",
		chat_path_key="openaiChatPath",
	),
	"litert-lm": ProviderConfigSpec(
		provider_id="litert-lm",
		model_key="litertModelName",
		model_default=defaults.DEFAULT_LITERT_MODEL,
		base_url_key="litertServerUrl",
		base_url_default=defaults.DEFAULT_LITERT_URL,
		litert_engine_settings=True,
	),
	"llama-cpp-server": ProviderConfigSpec(
		provider_id="llama-cpp-server",
		model_key="llamaCppModelName",
		model_default=defaults.DEFAULT_LLAMA_CPP_MODEL,
		base_url_key="llamaCppServerUrl",
		base_url_default=defaults.DEFAULT_LLAMA_CPP_URL,
		executable_key="llamaCppExecutable",
		executable_default=defaults.DEFAULT_LLAMA_CPP_EXECUTABLE,
		models_preset_key="llamaCppModelsPreset",
	),
}


def get_provider_config_spec(provider_id: str) -> ProviderConfigSpec | None:
	normalized = str(provider_id or "").strip().lower()
	if normalized == "openai_compat":
		return PROVIDER_CONFIG_SPECS["openai"]
	return PROVIDER_CONFIG_SPECS.get(normalized)


def get_provider_ids() -> frozenset[str]:
	return frozenset(PROVIDER_CONFIG_SPECS)
