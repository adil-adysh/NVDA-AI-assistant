# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..config.settings import get_active_provider_config
from ..providers.config import ProviderConfig
from ..providers.policy import get_provider_policy
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
	SERVER_NOT_READY = "server_not_ready"
	MISSING_CREDENTIALS = "missing_credentials"
	UNSUPPORTED_MODEL = "unsupported_model"
	UNSUPPORTED_PROVIDER = "unsupported_provider"


def get_provider_display_name(provider: str) -> str:
	"""Return the human-readable name for *provider*.

	Delegates to ``providers.registry.provider_display_name`` so the
	service layer does not duplicate the provider-name lookup.
	"""
	from ..providers.registry import provider_display_name as _display

	return _display(provider)


def is_gemini_generate_content_incompatible_model_name(model_name: str) -> bool:
	"""Backward-compatible helper backed by the declarative Gemini policy."""
	policy = get_provider_policy("gemini")
	return policy is not None and not policy.supports_model(model_name)


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
		policy = get_provider_policy(provider)

		if policy is None:
			return ProviderReadiness(
				provider=config.provider,
				state=ProviderReadinessState.INVALID_CONFIG,
				reason=ProviderReadinessReason.UNSUPPORTED_PROVIDER,
				can_infer=False,
				can_list_models=False,
			)

		if not model_name:
			return ProviderReadiness(
				provider=config.provider,
				state=ProviderReadinessState.UNCONFIGURED,
				reason=ProviderReadinessReason.MISSING_MODEL,
				can_infer=False,
				can_list_models=bool(base_url),
			)

		if policy.requires_runtime:
			supervisor = get_litert_supervisor()
			# Do not perform a socket request here. This method is called while
			# building NVDA/WebView state on the main thread, and is_healthy()
			# can wait several seconds while the model server is starting or
			# stopping. Chat readiness is established asynchronously by
			# ensure_litert_server_ready(); the UI can safely report a pending
			# provider until then.
			if not supervisor.is_running and not supervisor.is_adopted:
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

		if provider == "llama-cpp-server":
			if not base_url:
				return self._unconfigured(config.provider, ProviderReadinessReason.MISSING_SERVER_URL)
			from ..providers.llama_manager import LlamaCppModelManager

			manager = LlamaCppModelManager(config=config)
			record = manager.find_record(model_name)
			if record is None:
				return self._unconfigured(config.provider, ProviderReadinessReason.MISSING_MODEL)
			if not self._llama_server_is_ready(config, record):
				return ProviderReadiness(
					provider=config.provider,
					state=ProviderReadinessState.UNCONFIGURED,
					reason=ProviderReadinessReason.SERVER_NOT_READY,
					can_infer=False,
					can_list_models=True,
				)

		if not base_url:
			reason = (
				ProviderReadinessReason.MISSING_SERVER_URL
				if policy.kind == "local"
				else ProviderReadinessReason.MISSING_BASE_URL
			)
			return self._unconfigured(config.provider, reason)
		if not policy.has_credentials(config):
			return self._unconfigured(config.provider, ProviderReadinessReason.MISSING_CREDENTIALS)
		if not policy.supports_model(model_name):
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

	@staticmethod
	def _llama_server_is_ready(config: ProviderConfig, record: object) -> bool:
		from urllib.parse import urlparse

		from ..providers.runtime.llama_server import (
			DEFAULT_LLAMA_HOST,
			DEFAULT_LLAMA_PORT,
			default_llama_server_executable,
			get_llama_supervisor,
		)

		parsed = urlparse(str(getattr(config, "base_url", "") or ""))
		host = parsed.hostname or DEFAULT_LLAMA_HOST
		port = parsed.port or DEFAULT_LLAMA_PORT
		executable = str(getattr(config, "server_executable", "") or "").strip() or default_llama_server_executable()
		supervisor = get_llama_supervisor(executable, host, port)
		if supervisor.is_running or supervisor.is_adopted:
			return True
		if not supervisor.is_healthy():
			return False
		server_ids = {
			str(item.get("id", "")).strip()
			for item in supervisor.list_models()
			if str(item.get("id", "")).strip()
		}
		identities = {
			str(getattr(record, "model_id", "")),
			str(getattr(record, "source", "")),
			str(getattr(record, "server_model", "")),
			str(getattr(record, "server_model", "")).removeprefix("hf://"),
		}
		variant = str(getattr(record, "variant", "") or "").strip()
		if variant:
			identities.add(f"{getattr(record, 'source', '')}:{variant}")
		return bool(server_ids.intersection(identities))
