# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..config.settings import get_active_provider_config
from ..providers.config import ProviderConfig
from ..providers.policy import get_provider_policy
from ..providers.runtime.server import get_litert_supervisor


class ModelCatalogAuthority(str, Enum):
	"""Defines whether a provider's model catalog is authoritative or advisory."""

	AUTHORITATIVE = "authoritative"  # Local runtimes: model must be downloaded/imported
	ADVISORY = "advisory"            # Cloud endpoints: model list is advisory, custom models valid
	NONE = "none"                    # No catalog discovery support


class ConfiguredModelState(str, Enum):
	"""Lifecycle status of the configured model."""

	VALID = "valid"                    # Model exists in catalog and is enabled
	NOT_CONFIGURED = "not_configured"  # Model string is empty
	UNAVAILABLE = "unavailable"        # Model missing from authoritative catalog / not downloaded
	DISABLED = "disabled"              # Model is explicitly disabled by user
	UNKNOWN = "unknown"                # Catalog is cold or loading, cannot verify yet


@dataclass(frozen=True, slots=True)
class ConfiguredModelStatus:
	model_id: str
	state: ConfiguredModelState
	authority: ModelCatalogAuthority
	reason: str | None = None
	can_infer: bool = True


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
	MODEL_UNAVAILABLE = "model_unavailable"
	MODEL_DISABLED = "model_disabled"


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
	model_name: str | None = None
	model_status: ConfiguredModelStatus | None = None

	@property
	def is_ready(self) -> bool:
		return self.state == ProviderReadinessState.READY

	@property
	def requires_configuration(self) -> bool:
		return self.state != ProviderReadinessState.READY


class ProviderReadinessService:
	"""Evaluates runtime readiness and configured model validity."""

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
				model_name=model_name,
			)

		authority = self._resolve_authority(provider, policy)

		if not model_name:
			status = ConfiguredModelStatus(
				model_id="",
				state=ConfiguredModelState.NOT_CONFIGURED,
				authority=authority,
				can_infer=False,
			)
			return ProviderReadiness(
				provider=config.provider,
				state=ProviderReadinessState.UNCONFIGURED,
				reason=ProviderReadinessReason.MISSING_MODEL,
				can_infer=False,
				can_list_models=bool(base_url),
				model_name="",
				model_status=status,
			)

		# Check if model has been explicitly disabled by user
		try:
			from ..config.enabled_models import ModelVisibilityStore

			visibility = ModelVisibilityStore()
			if not visibility.is_model_visible(provider, model_name):
				status = ConfiguredModelStatus(
					model_id=model_name,
					state=ConfiguredModelState.DISABLED,
					authority=authority,
					reason="Model is disabled in settings",
					can_infer=False,
				)
				return ProviderReadiness(
					provider=config.provider,
					state=ProviderReadinessState.INVALID_CONFIG,
					reason=ProviderReadinessReason.MODEL_DISABLED,
					can_infer=False,
					can_list_models=True,
					model_name=model_name,
					model_status=status,
				)
		except Exception:
			pass

		if policy.requires_runtime:
			supervisor = get_litert_supervisor()
			if not supervisor.is_running and not supervisor.is_adopted:
				return ProviderReadiness(
					provider=config.provider,
					state=ProviderReadinessState.UNCONFIGURED,
					reason=ProviderReadinessReason.MISSING_SERVER_URL,
					can_infer=False,
					can_list_models=False,
					model_name=model_name,
				)
			# For LiteRT, check authoritative catalog if populated
			from .model_cache import model_catalog_cache, CatalogState

			snapshot = model_catalog_cache.get_snapshot("litert-lm")
			if snapshot.state in (CatalogState.READY, CatalogState.EMPTY):
				available_ids = {m.id.lower() for m in snapshot.models}
				from ..providers.litert_models import resolve_identity

				resolved = resolve_identity(model_name).lower()
				if resolved not in available_ids and model_name.lower() not in available_ids:
					status = ConfiguredModelStatus(
						model_id=model_name,
						state=ConfiguredModelState.UNAVAILABLE,
						authority=ModelCatalogAuthority.AUTHORITATIVE,
						reason="Model is not available or imported in LiteRT runtime",
						can_infer=False,
					)
					return ProviderReadiness(
						provider=config.provider,
						state=ProviderReadinessState.INVALID_CONFIG,
						reason=ProviderReadinessReason.MODEL_UNAVAILABLE,
						can_infer=False,
						can_list_models=True,
						model_name=model_name,
						model_status=status,
					)

			status = ConfiguredModelStatus(
				model_id=model_name,
				state=ConfiguredModelState.VALID,
				authority=ModelCatalogAuthority.AUTHORITATIVE,
				can_infer=True,
			)
			return ProviderReadiness(
				provider=config.provider,
				state=ProviderReadinessState.READY,
				reason=None,
				can_infer=True,
				can_list_models=True,
				model_name=model_name,
				model_status=status,
			)

		if provider == "llama-cpp-server":
			if not base_url:
				return self._unconfigured(config.provider, ProviderReadinessReason.MISSING_SERVER_URL, model_name=model_name)
			from ..providers.llama_manager import LlamaCppModelManager

			manager = LlamaCppModelManager(config=config)
			record = manager.find_record(model_name)
			server_items = manager.list_server_models() if record is None else ()
			server_exposed = any(
				str(item.get("id", "")).strip().lower() == model_name.lower()
				for item in server_items
			)
			if record is None and not server_exposed:
				status = ConfiguredModelStatus(
					model_id=model_name,
					state=ConfiguredModelState.UNAVAILABLE,
					authority=ModelCatalogAuthority.AUTHORITATIVE,
					reason="Model is not found in llama-server catalog",
					can_infer=False,
				)
				return ProviderReadiness(
					provider=config.provider,
					state=ProviderReadinessState.INVALID_CONFIG,
					reason=ProviderReadinessReason.MODEL_UNAVAILABLE,
					can_infer=False,
					can_list_models=True,
					model_name=model_name,
					model_status=status,
				)
			if not self._llama_server_is_ready(config, record):
				return ProviderReadiness(
					provider=config.provider,
					state=ProviderReadinessState.UNCONFIGURED,
					reason=ProviderReadinessReason.SERVER_NOT_READY,
					can_infer=False,
					can_list_models=True,
					model_name=model_name,
				)

		if not base_url:
			reason = (
				ProviderReadinessReason.MISSING_SERVER_URL
				if policy.kind == "local"
				else ProviderReadinessReason.MISSING_BASE_URL
			)
			return self._unconfigured(config.provider, reason, model_name=model_name)
		if not policy.has_credentials(config):
			return self._unconfigured(config.provider, ProviderReadinessReason.MISSING_CREDENTIALS, model_name=model_name)
		if not policy.supports_model(model_name):
			status = ConfiguredModelStatus(
				model_id=model_name,
				state=ConfiguredModelState.UNAVAILABLE,
				authority=authority,
				reason="Model is not supported by provider policy",
				can_infer=False,
			)
			return ProviderReadiness(
				provider=config.provider,
				state=ProviderReadinessState.INVALID_CONFIG,
				reason=ProviderReadinessReason.UNSUPPORTED_MODEL,
				can_infer=False,
				can_list_models=True,
				model_name=model_name,
				model_status=status,
			)

		status = ConfiguredModelStatus(
			model_id=model_name,
			state=ConfiguredModelState.VALID,
			authority=authority,
			can_infer=True,
		)
		return ProviderReadiness(
			provider=config.provider,
			state=ProviderReadinessState.READY,
			reason=None,
			can_infer=True,
			can_list_models=True,
			model_name=model_name,
			model_status=status,
		)

	def evaluate_active(self) -> ProviderReadiness:
		return self.evaluate(get_active_provider_config())

	def _unconfigured(
		self,
		provider: str,
		reason: ProviderReadinessReason,
		model_name: str | None = None,
	) -> ProviderReadiness:
		return ProviderReadiness(
			provider=provider,
			state=ProviderReadinessState.UNCONFIGURED,
			reason=reason,
			can_infer=False,
			can_list_models=False,
			model_name=model_name,
		)

	@staticmethod
	def _resolve_authority(provider: str, policy: object) -> ModelCatalogAuthority:
		if provider in {"litert-lm", "llama-cpp", "llama-cpp-server"}:
			return ModelCatalogAuthority.AUTHORITATIVE
		if getattr(policy, "kind", "") == "local":
			return ModelCatalogAuthority.AUTHORITATIVE
		if provider in {"openai", "gemini", "openrouter", "ollama", "anthropic"}:
			return ModelCatalogAuthority.ADVISORY
		return ModelCatalogAuthority.NONE

	@staticmethod
	def _llama_server_is_ready(config: ProviderConfig, record: object | None = None) -> bool:
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
		if record is None:
			return True
		return any(record.matches_server_id(str(item.get("id", ""))) for item in supervisor.list_models())
