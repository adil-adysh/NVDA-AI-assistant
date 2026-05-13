# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..config.settings import get_active_provider_config
from ..providers.config import GeminiConfig, OllamaConfig, OpenAIConfig, ProviderConfig


class ProviderReadinessState(str, Enum):
	UNCONFIGURED = "unconfigured"
	INVALID_CONFIG = "invalid_config"
	READY = "ready"


class ProviderReadinessReason(str, Enum):
	MISSING_MODEL = "missing_model"
	MISSING_SERVER_URL = "missing_server_url"
	MISSING_BASE_URL = "missing_base_url"
	MISSING_CHAT_PATH = "missing_chat_path"
	MISSING_CREDENTIALS = "missing_credentials"
	UNSUPPORTED_MODEL = "unsupported_model"


def get_provider_display_name(provider: str) -> str:
	normalized = str(provider or "").strip().lower()
	# TRANSLATORS: Display name for the OpenAI provider shown in status messages.
	if normalized == "openai":
		return "OpenAI"
	# TRANSLATORS: Display name for the Gemini provider shown in status messages.
	if normalized == "gemini":
		return "Gemini"
	# TRANSLATORS: Display name for the Ollama provider shown in status messages.
	return "Ollama"


def is_gemini_generate_content_incompatible_model_name(model_name: str) -> bool:
	normalized = str(model_name or "").strip().lower()
	return any(
		marker in normalized
		for marker in (
			"live-preview",
			"deep-research-preview",
			"deep-research-max-preview",
		)
	)


@dataclass(frozen=True, slots=True)
class ProviderReadiness:
	provider: str
	state: ProviderReadinessState
	reason: ProviderReadinessReason | None
	can_infer: bool
	can_list_models: bool

	@property
	def is_ready(self) -> bool:
		return self.state == ProviderReadinessState.READY

	@property
	def requires_configuration(self) -> bool:
		return self.state != ProviderReadinessState.READY


class ProviderReadinessService:
	def evaluate(self, config: ProviderConfig) -> ProviderReadiness:
		if isinstance(config, OllamaConfig):
			return self._evaluate_ollama(config)
		if isinstance(config, GeminiConfig):
			return self._evaluate_gemini(config)
		if isinstance(config, OpenAIConfig):
			return self._evaluate_openai(config)
		raise ValueError(f"Unsupported provider config type: {type(config).__name__}")

	def evaluate_active(self) -> ProviderReadiness:
		return self.evaluate(get_active_provider_config())

	def _evaluate_ollama(self, config: OllamaConfig) -> ProviderReadiness:
		model_name = str(config.model_name or "").strip()
		server_url = str(config.server_url or "").strip()
		if not model_name:
			return ProviderReadiness(
				provider=config.provider,
				state=ProviderReadinessState.UNCONFIGURED,
				reason=ProviderReadinessReason.MISSING_MODEL,
				can_infer=False,
				can_list_models=bool(server_url),
			)
		if not server_url:
			return ProviderReadiness(
				provider=config.provider,
				state=ProviderReadinessState.UNCONFIGURED,
				reason=ProviderReadinessReason.MISSING_SERVER_URL,
				can_infer=False,
				can_list_models=False,
			)
		return ProviderReadiness(
			provider=config.provider,
			state=ProviderReadinessState.READY,
			reason=None,
			can_infer=True,
			can_list_models=True,
		)

	def _evaluate_gemini(self, config: GeminiConfig) -> ProviderReadiness:
		model_name = str(config.model_name or "").strip()
		base_url = str(config.base_url or "").strip()
		api_key = str(config.api_key or "").strip()
		api_token = str(config.api_token or "").strip()
		if not model_name:
			return self._unconfigured(config.provider, ProviderReadinessReason.MISSING_MODEL)
		if not base_url:
			return self._unconfigured(config.provider, ProviderReadinessReason.MISSING_BASE_URL)
		if not api_key and not api_token:
			return self._unconfigured(config.provider, ProviderReadinessReason.MISSING_CREDENTIALS)
		if is_gemini_generate_content_incompatible_model_name(model_name):
			return ProviderReadiness(
				provider=config.provider,
				state=ProviderReadinessState.INVALID_CONFIG,
				reason=ProviderReadinessReason.UNSUPPORTED_MODEL,
				can_infer=False,
				can_list_models=True,
			)
		return ProviderReadiness(
			provider=config.provider,
			state=ProviderReadinessState.READY,
			reason=None,
			can_infer=True,
			can_list_models=True,
		)

	def _evaluate_openai(self, config: OpenAIConfig) -> ProviderReadiness:
		model_name = str(config.model_name or "").strip()
		base_url = str(config.base_url or "").strip()
		chat_path = str(config.chat_path or "").strip()
		api_key = str(config.api_key or "").strip()
		if not model_name:
			return self._unconfigured(config.provider, ProviderReadinessReason.MISSING_MODEL)
		if not base_url:
			return self._unconfigured(config.provider, ProviderReadinessReason.MISSING_BASE_URL)
		if not chat_path:
			return self._unconfigured(config.provider, ProviderReadinessReason.MISSING_CHAT_PATH)
		if not api_key:
			return self._unconfigured(config.provider, ProviderReadinessReason.MISSING_CREDENTIALS)
		return ProviderReadiness(
			provider=config.provider,
			state=ProviderReadinessState.READY,
			reason=None,
			can_infer=True,
			can_list_models=True,
		)

	def _unconfigured(self, provider: str, reason: ProviderReadinessReason) -> ProviderReadiness:
		return ProviderReadiness(
			provider=provider,
			state=ProviderReadinessState.UNCONFIGURED,
			reason=reason,
			can_infer=False,
			can_list_models=False,
		)
