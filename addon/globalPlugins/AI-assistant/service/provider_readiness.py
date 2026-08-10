# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..config.settings import get_active_provider_config
from ..providers.config import ProviderConfig
from ..providers.runtime.server import get_litert_supervisor


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
	"""Return the human-readable name for *provider*.

	Delegates to ``providers.registry.provider_display_name`` so the
	service layer does not duplicate the provider-name lookup.
	"""
	from ..providers.registry import provider_display_name as _display

	return _display(provider)


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
	# evaluate() is a guard chain that returns as soon as the first missing
	# requirement is found; the many early returns are the point of the
	# function, not an accident.
	def evaluate(self, config: ProviderConfig) -> ProviderReadiness:  # pylint: disable=too-many-return-statements
		provider = str(config.provider or "").strip().lower()
		model_name = str(config.model_name or "").strip()
		base_url = str(getattr(config, "base_url", "") or "").strip()
		api_key = str(getattr(config, "api_key", "") or "").strip()

		if not model_name:
			from ..providers.registry import PROVIDER_IDS

			can_list = provider in PROVIDER_IDS
			return ProviderReadiness(
				provider=config.provider,
				state=ProviderReadinessState.UNCONFIGURED,
				reason=ProviderReadinessReason.MISSING_MODEL,
				can_infer=False,
				can_list_models=can_list or bool(base_url),
			)

		# LiteRT: local server must be healthy.
		if provider == "litert-lm":
			supervisor = get_litert_supervisor()
			# Do not perform a socket request here. This method is called while
			# building NVDA/WebView state on the main thread, and is_healthy()
			# can wait several seconds while the model server is starting or
			# stopping. Chat readiness is established asynchronously by
			# ensure_litert_server_ready(); the UI can safely report a pending
			# provider until then.
			if not supervisor.is_running:
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

		# Ollama: needs server URL, no credentials.
		if provider == "ollama":
			if not base_url:
				return self._unconfigured(config.provider, ProviderReadinessReason.MISSING_SERVER_URL)
			return ProviderReadiness(
				provider=config.provider,
				state=ProviderReadinessState.READY,
				reason=None,
				can_infer=True,
				can_list_models=True,
			)

		# Gemini: needs base URL + credentials (API key or bearer token).
		if provider == "gemini":
			if not base_url:
				return self._unconfigured(config.provider, ProviderReadinessReason.MISSING_BASE_URL)
			api_token = str(getattr(config, "api_token", "") or "").strip()
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

		# OpenAI / generic: needs base URL + API key.
		if provider in {"openai", "openai_compat"} or not provider:
			if not base_url:
				return self._unconfigured(config.provider, ProviderReadinessReason.MISSING_BASE_URL)
			if not api_key and provider != "openai_compat":
				return self._unconfigured(config.provider, ProviderReadinessReason.MISSING_CREDENTIALS)
			return ProviderReadiness(
				provider=config.provider,
				state=ProviderReadinessState.READY,
				reason=None,
				can_infer=True,
				can_list_models=True,
			)

		# Unknown provider: assume ready if model + URL present.
		if model_name and base_url:
			return ProviderReadiness(
				provider=config.provider,
				state=ProviderReadinessState.READY,
				reason=None,
				can_infer=True,
				can_list_models=True,
			)

		raise ValueError(f"Unsupported provider config type: {type(config).__name__}")

	def evaluate_active(self) -> ProviderReadiness:
		return self.evaluate(get_active_provider_config())

	def _unconfigured(self, provider: str, reason: ProviderReadinessReason) -> ProviderReadiness:
		return ProviderReadiness(
			provider=provider,
			state=ProviderReadinessState.UNCONFIGURED,
			reason=reason,
			can_infer=False,
			can_list_models=False,
		)
