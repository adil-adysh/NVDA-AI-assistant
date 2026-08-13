# -*- coding: utf-8 -*-
"""Model manager types — shared between providers and the UI.

Defines the ``ModelManagerProvider`` protocol that cloud and local
providers implement, plus the ``ManagedModel`` and ``ModelState``
types consumed by the model manager dialog.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
	from ..service.model_cache import ModelCapabilityCache
	from ..service.model_cache import ModelCatalogCache

from .policy import get_provider_policy
from .model_import import ModelImportRequest


# ── Type aliases ────────────────────────────────────────────────────

DownloadProgressCallback = Callable[[str, int | None, int | None], None]
"""``(message, downloaded_bytes, total_bytes)`` — called during download."""


class ModelState(str, Enum):
	"""Availability of a model for inference.

	Local providers use ``DOWNLOADED`` / ``NOT_DOWNLOADED`` /
	``DOWNLOADING`` / ``FAILED``.  Cloud providers use ``READY``.
	"""

	READY = "ready"  # cloud — always available
	DOWNLOADED = "downloaded"  # local — on disk
	NOT_DOWNLOADED = "not_downloaded"  # local — known but absent
	DOWNLOADING = "downloading"  # local — in progress
	FAILED = "failed"  # local — download errored

	def is_ready(self) -> bool:
		"""Can this model actually perform inference right now?"""
		return self in (ModelState.READY, ModelState.DOWNLOADED)


@dataclass(frozen=True)
class ManagedModel:
	"""A model known to a provider, with runtime state and metadata.

	The model manager dialog renders these, the settings combo and host
	UI dropdown filter on ``enabled and state.is_ready()``.
	"""

	id: str  # provider-specific identifier
	display_name: str  # human-readable label
	state: ModelState
	priority: int = 100  # lower → more recommended (10 = default model)
	size_hint: str = ""
	capabilities: tuple[str, ...] = field(default_factory=tuple)
	description: str = ""  # plain-text description for the details panel
	canonical_id: str = ""  # owning model's canonical ID (set for variant entries)


@dataclass(frozen=True)
class ProviderFeatures:
	"""Capabilities advertised by a provider to the model manager UI.

	These control which action buttons are shown / enabled.
	"""

	download: bool = False
	delete: bool = False
	import_model: bool = False


@runtime_checkable
class ModelManagerProvider(Protocol):
	"""Protocol for providers that support model management.

	Cloud providers return ``ModelState.READY`` for all models and set
	``features.download = False``.  Local providers drive model state
	from the filesystem and support download / delete.
	"""

	provider_id: str
	features: ProviderFeatures
	active_model_id: str | None

	def list_managed_models(self) -> list[ManagedModel]:
		"""Return the complete model catalog with current states."""
		...

	def download_model(
		self,
		model_id: str,
		on_progress: DownloadProgressCallback,
		cancel_event: threading.Event | None = None,
	) -> None:
		"""Download *model_id* to the local cache.

		*on_progress* is called with ``(message, downloaded_bytes, total_bytes)``
		where the byte values may be ``None`` when the total size is unknown.

		*cancel_event* (optional) allows the caller to request cancellation;
		the partial file is preserved for future resume.

		Runs in a **background thread** — callers must dispatch UI
		updates via ``wx.CallAfter`` or equivalent.
		"""
		...

	def delete_model(self, model_id: str) -> None:
		"""Remove the cached file for *model_id*."""
		...

	def import_model(
		self,
		request: ModelImportRequest,
		on_progress: DownloadProgressCallback,
		cancel_event: threading.Event | None = None,
	) -> None:
		"""Import a local file or remote model reference into the provider."""
		...

	def set_active_model(self, model_id: str) -> None:
		"""Persist *model_id* as the active model for this provider."""
		...

	def get_available_model_ids(self) -> list[str]:
		"""Return model IDs that are ready for use in the UI dropdown.

		Cloud providers return all listed model IDs (always READY).
		Local providers return only models whose files are on disk
		or have been imported into the runtime catalog.

		This is the **single source of truth** for "what models appear
		in the WebView dropdown and settings combo" — callers must not
		re-implement readiness checks.
		"""
		...

	def resolve_model_identity(self, model_id: str) -> str:
		"""Normalise *model_id* to its canonical provider identity.

		For local providers with variant filenames, this resolves a
		variant filename back to the canonical model ID (e.g. Hugging
		Face repo ID).  Cloud providers return *model_id* unchanged.
		"""
		...


class CloudModelManagerAdapter:
	"""Adapts a cloud LLMProvider to the ModelManagerProvider protocol.

	Cloud models are always ``READY`` — there is nothing to download
	or delete.  The adapter delegates ``list_models()`` to the wrapped
	provider and routes ``set_active_model`` through the supplied
	setter callable.
	"""

	def __init__(
		self,
		provider_id: str,
		config: Any,
		provider_class: Any,
		set_model_fn: Callable[[str], None],
		get_config_fn: Callable[[], Any] | None = None,
		model_cache: ModelCatalogCache | None = None,
		capability_cache: ModelCapabilityCache | None = None,
	) -> None:
		self.provider_id = provider_id
		self._config = config
		self._provider_class = provider_class
		self._set_model_fn = set_model_fn
		self._get_config_fn = get_config_fn
		self._model_cache = model_cache
		self._capability_cache = capability_cache
		self._cached_models: list[ManagedModel] | None = None
		self._cache_lock = threading.Lock()

	@property
	def features(self) -> ProviderFeatures:
		return ProviderFeatures(download=False, delete=False)

	@property
	def active_model_id(self) -> str | None:
		# Re-read config so set_active_model() is reflected immediately
		cfg = self._config
		if self._get_config_fn is not None:
			try:
				cfg = self._get_config_fn()
			except Exception:
				pass
		return str(cfg.model_name or "").strip() or None

	def list_managed_models(self) -> list[ManagedModel]:
		"""Fetch models from the cloud provider (cached for dialog lifetime).

		If a ``ModelCatalogCache`` is available, uses it as the first
		data source — this avoids a network round-trip when the cache
		was preloaded at startup.  Falls back to a direct provider call
		when the cache is cold or unavailable.
		"""
		with self._cache_lock:
			if self._cached_models is not None:
				return self._cached_models

		# 1. Try the central model cache (populated at startup).
		if self._model_cache is not None:
			cached_info = self._model_cache.get_models_or_empty(self.provider_id)
			if cached_info:
				result = self._convert_to_managed(cached_info)
				with self._cache_lock:
					self._cached_models = result
				return result

		# 2. Fall back to direct provider call.
		try:
			provider = self._provider_class(config=self._config)
			try:
				raw = provider.list_models()
			finally:
				provider.close()
		except Exception:
			return []
		result = self._convert_to_managed(raw)
		with self._cache_lock:
			self._cached_models = result
		return result

	def _convert_to_managed(
		self,
		raw: tuple[Any, ...] | list[Any],
	) -> list[ManagedModel]:
		"""Convert ``ProviderModelInfo`` items to ``ManagedModel``."""
		result: list[ManagedModel] = []
		policy = get_provider_policy(self.provider_id)
		for m in raw:
			model_id = m.id
			if policy is not None and not policy.supports_model(model_id):
				continue
			capabilities = m.capabilities
			if not capabilities and self._capability_cache is not None:
				capabilities = tuple(
					self._capability_cache.get(self.provider_id, model_id).values,
				)
			result.append(
				ManagedModel(
					id=model_id,
					display_name=m.display_name or model_id,
					state=ModelState.READY,
					capabilities=capabilities,
				)
			)
		return result

	def download_model(
		self,
		model_id: str,
		on_progress: DownloadProgressCallback,
		cancel_event: threading.Event | None = None,
	) -> None:
		raise NotImplementedError("Cloud providers do not support model download")

	def import_model(
		self,
		request: ModelImportRequest,
		on_progress: DownloadProgressCallback,
		cancel_event: threading.Event | None = None,
	) -> None:
		raise NotImplementedError("Cloud providers do not support model import")

	def delete_model(self, model_id: str) -> None:
		raise NotImplementedError("Cloud providers do not support model delete")

	def set_active_model(self, model_id: str) -> None:
		self._set_model_fn(model_id)

	def get_available_model_ids(self) -> list[str]:
		"""Return all listed model IDs (cloud models are always READY)."""
		return [m.id for m in self.list_managed_models()]

	def resolve_model_identity(self, model_id: str) -> str:
		"""Cloud providers use model IDs as-is — no variant resolution."""
		return model_id
