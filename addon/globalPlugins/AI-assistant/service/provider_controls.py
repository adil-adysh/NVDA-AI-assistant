# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..config.settings import (
	get_enabled_providers,
	get_provider,
	get_provider_state,
	save,
	set_model_name,
	set_provider,
	set_think,
)
from ..config.state import ProviderState
from ..providers.interfaces import ProviderModelInfo
from ..providers.registry import PROVIDER_IDS
from .provider_readiness import ProviderReadiness, ProviderReadinessService

if TYPE_CHECKING:
	from ..config.enabled_models import EnabledModelsStore
	from .model_cache import ModelCatalogCache


@dataclass(frozen=True, slots=True)
class ProviderControlResult:
	provider_state: ProviderState
	readiness: ProviderReadiness


@dataclass(frozen=True, slots=True)
class ModelSwitchResult:
	"""Result of a model/provider switch operation.

	Carries everything the gesture layer needs to announce the change.
	"""
	provider_id: str
	provider_display_name: str
	model_id: str
	model_display_name: str
	control_result: ProviderControlResult


class ProviderControlService:
	# Canonical provider order/identity comes from the provider registry.
	PROVIDER_ORDER = PROVIDER_IDS

	def __init__(
		self,
		readiness_service: ProviderReadinessService | None = None,
		model_cache: ModelCatalogCache | None = None,
		enabled_store: EnabledModelsStore | None = None,
	) -> None:
		self._readiness_service = readiness_service or ProviderReadinessService()
		self._model_cache = model_cache  # set later if not provided
		self._enabled_store = enabled_store  # set later if not provided

	# ------------------------------------------------------------------
	# Dependencies (lazy to avoid circular imports)
	# ------------------------------------------------------------------

	def _get_model_cache(self) -> ModelCatalogCache:
		if self._model_cache is None:
			from .model_cache import model_catalog_cache
			self._model_cache = model_catalog_cache
		return self._model_cache

	def _get_enabled_store(self) -> EnabledModelsStore:
		if self._enabled_store is None:
			from ..config.enabled_models import EnabledModelsStore
			self._enabled_store = EnabledModelsStore()
		return self._enabled_store

	# ------------------------------------------------------------------
	# State queries
	# ------------------------------------------------------------------

	def current_state(self) -> ProviderControlResult:
		return ProviderControlResult(
			provider_state=get_provider_state(),
			readiness=self._readiness_service.evaluate_active(),
		)

	# ------------------------------------------------------------------
	# Model listing (from cache)
	# ------------------------------------------------------------------

	def list_models(self, provider_id: str) -> tuple[ProviderModelInfo, ...]:
		"""Return all models for *provider_id* from the cache.

		If the cache is cold for this provider, this will block briefly
		while fetching from the network.  Call from a background thread
		or ensure ``preload_async`` has been called first.
		"""
		return self._get_model_cache().get_models(self._normalize_provider_id(provider_id))

	def list_models_cached(self, provider_id: str) -> tuple[ProviderModelInfo, ...]:
		"""Return models from cache, or ``()`` if not yet populated.

		Never blocks — safe for the NVDA main thread.
		"""
		return self._get_model_cache().get_models_or_empty(self._normalize_provider_id(provider_id))

	def refresh_models(self, provider_id: str) -> tuple[ProviderModelInfo, ...]:
		"""Refresh and return the authoritative catalog for *provider_id*.

		Local providers expose dynamic server registries, so a result cached
		before their server starts must not hide models that are now ready.
		"""
		provider_id = self._normalize_provider_id(provider_id)
		cache = self._get_model_cache()
		cache.invalidate(provider_id)
		return cache.get_models(provider_id)

	def list_enabled_models(
		self,
		provider_id: str,
		auto_register_new: bool = True,
	) -> tuple[ProviderModelInfo, ...]:
		"""Return models visible to the user for *provider_id*.

		Filters to only user-enabled models.  When *auto_register_new*
		is ``True`` (default), newly discovered models are registered
		as enabled; only models the user has explicitly disabled are
		hidden.
		"""
		provider_id = self._normalize_provider_id(provider_id)
		models = self.list_models(provider_id)
		if not models:
			return ()
		store = self._get_enabled_store()
		enabled_ids = store.get_enabled(provider_id)
		if auto_register_new and enabled_ids:
			for m in models:
				if m.id not in enabled_ids:
					store.set_enabled(provider_id, m.id, True)
			enabled_ids = store.get_enabled(provider_id)
		elif not enabled_ids:
			# No stored preferences — show all models.
			return models
		return tuple(m for m in models if m.id in enabled_ids)

	def get_model_display_name(
		self,
		model_id: str,
		provider_id: str | None = None,
	) -> str:
		"""Resolve a human-readable display name for *model_id*.

		Looks up the model in the cache for *provider_id* (or the
		current provider if ``None``).  Falls back to *model_id* if
		the model is not found.
		"""
		pid = provider_id or get_provider()
		models = self._get_model_cache().get_models_or_empty(pid)
		for m in models:
			if m.id == model_id:
				return m.display_name or m.id
		return model_id

	# ------------------------------------------------------------------
	# Provider switching
	# ------------------------------------------------------------------

	def select_provider(self, provider: str) -> ProviderControlResult:
		enabled = get_enabled_providers()
		if provider not in enabled:
			raise ValueError(
				f"Provider '{provider}' is disabled. Enabled providers: {enabled}"
			)
		set_provider(provider)
		save()
		return self.current_state()

	def cycle_provider(self) -> ProviderControlResult:
		current_provider = get_provider()
		enabled = get_enabled_providers()
		cycle_order = [p for p in self.PROVIDER_ORDER if p in enabled]
		if not cycle_order:
			return self.current_state()
		if current_provider not in cycle_order:
			target_provider = cycle_order[0]
		else:
			idx = cycle_order.index(current_provider)
			target_provider = cycle_order[(idx + 1) % len(cycle_order)]
		return self.select_provider(target_provider)

	# ------------------------------------------------------------------
	# Model switching
	# ------------------------------------------------------------------

	def select_model(
		self,
		model: str,
		provider: str | None = None,
	) -> ModelSwitchResult:
		"""Switch to *model* and return a result suitable for announcement.

		Resolves display names for both the provider and model from the
		registry and cache respectively.
		"""
		if provider:
			self.select_provider(provider)
		set_model_name(model)
		save()
		control = self.current_state()
		pid = control.provider_state.provider
		provider_label = self._resolve_provider_display_name(pid)
		model_label = self.get_model_display_name(model, pid)
		return ModelSwitchResult(
			provider_id=pid,
			provider_display_name=provider_label,
			model_id=model,
			model_display_name=model_label,
			control_result=control,
		)

	def set_think_mode(self, enabled: bool) -> ProviderControlResult:
		provider = get_provider()
		state = get_provider_state()
		set_think(provider, enabled, model_id=state.model_name)
		save()
		return self.current_state()

	# ------------------------------------------------------------------
	# Helpers
	# ------------------------------------------------------------------

	@staticmethod
	def _resolve_provider_display_name(provider_id: str) -> str:
		from .provider_readiness import get_provider_display_name
		return get_provider_display_name(provider_id)

	@staticmethod
	def _normalize_provider_id(provider_id: str) -> str:
		return str(provider_id or "").strip().lower()


provider_control_service = ProviderControlService()
