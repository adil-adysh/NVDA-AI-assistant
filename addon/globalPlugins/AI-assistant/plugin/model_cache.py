# -*- coding: utf-8 -*-
from __future__ import annotations

import threading
from collections.abc import Callable

from logHandler import log

from ..config.state import ProviderState
from ..service.provider_catalog import ProviderCatalogService


class ModelCache:
	"""Thread-safe cache for available provider models with async refresh."""

	def __init__(
		self,
		provider_catalog: ProviderCatalogService,
		on_models_updated: Callable[[str, tuple[str, ...]], None] | None = None,
	) -> None:
		self._provider_catalog = provider_catalog
		self._on_models_updated = on_models_updated
		self._available_models_by_provider: dict[str, tuple[str, ...]] = {}
		self._lock = threading.RLock()

	def close(self) -> None:
		self._on_models_updated = None
		self._available_models_by_provider.clear()

	def get(self, provider_state: ProviderState) -> tuple[str, ...]:
		with self._lock:
			return self._available_models_by_provider.get(provider_state.provider, ())

	def refresh_async(self, provider_state: ProviderState) -> None:
		threading.Thread(
			target=self._refresh,
			args=(provider_state,),
			name=f"ModelCacheRefresh-{provider_state.provider}",
			daemon=True,
		).start()

	def _refresh(self, provider_state: ProviderState) -> None:
		from ..config.settings import get_provider_state
		from ..providers.registry import build_model_manager

		current = get_provider_state()
		if current.provider != provider_state.provider:
			log.debug(
				"Skipping stale model refresh for %s; active provider is %s",
				provider_state.provider,
				current.provider,
			)
			return

		try:
			mgr = build_model_manager(provider_state.provider)
			models = tuple(mgr.get_available_model_ids())
		except Exception:
			log.exception("Error refreshing provider models for %s", provider_state.provider)
			return

		if not models:
			return

		current = get_provider_state()
		if current.provider != provider_state.provider:
			log.debug(
				"Discarding stale model refresh result for %s; active provider is %s",
				provider_state.provider,
				current.provider,
			)
			return

		with self._lock:
			self._available_models_by_provider[provider_state.provider] = models

		if self._on_models_updated is not None:
			try:
				self._on_models_updated(provider_state.provider, models)
			except Exception:
				log.exception("Error in model cache on_models_updated callback")
