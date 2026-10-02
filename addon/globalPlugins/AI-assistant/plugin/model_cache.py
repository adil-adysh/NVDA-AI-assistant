# -*- coding: utf-8 -*-
"""Compatibility wrapper around centralized ModelCatalogCache."""

from __future__ import annotations

from collections.abc import Callable

from ..config.state import ProviderState
from ..service.provider_catalog import ProviderCatalogService
from ..service.model_cache import model_catalog_cache, ModelCatalogSnapshot


class ModelCache:
	"""Deprecated compatibility wrapper around centralized ModelCatalogCache."""

	def __init__(
		self,
		provider_catalog: ProviderCatalogService | None = None,
		on_models_updated: Callable[[str, tuple[str, ...]], None] | None = None,
	) -> None:
		self._provider_catalog = provider_catalog
		self._on_models_updated = on_models_updated
		self._unsubscribe = None
		if on_models_updated is not None:
			def _adapter(provider_id: str, snapshot: ModelCatalogSnapshot) -> None:
				if self._on_models_updated is not None:
					self._on_models_updated(provider_id, tuple(m.id for m in snapshot.models))
			self._unsubscribe = model_catalog_cache.subscribe(_adapter)

	def close(self) -> None:
		if self._unsubscribe is not None:
			self._unsubscribe()
			self._unsubscribe = None
		self._on_models_updated = None

	def get(self, provider_state: ProviderState) -> tuple[str, ...]:
		return tuple(m.id for m in model_catalog_cache.get_models_or_empty(provider_state.provider))

	def refresh_async(self, provider_state: ProviderState) -> None:
		model_catalog_cache.refresh_async(provider_state.provider)
