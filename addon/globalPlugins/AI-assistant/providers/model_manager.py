# -*- coding: utf-8 -*-
"""Model manager types — shared between providers and the UI.

Defines the ``ModelManagerProvider`` protocol that cloud and local
providers implement, plus the ``ManagedModel`` and ``ModelState``
types consumed by the model manager dialog.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


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


@dataclass(frozen=True)
class ProviderFeatures:
	"""Capabilities advertised by a provider to the model manager UI.

	These control which action buttons are shown / enabled.
	"""

	download: bool = False
	delete: bool = False


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
	) -> None:
		"""Download *model_id* to the local cache.

		*on_progress* is called with ``(message, downloaded_bytes, total_bytes)``
		where the byte values may be ``None`` when the total size is unknown.

		Runs in a **background thread** — callers must dispatch UI
		updates via ``wx.CallAfter`` or equivalent.
		"""
		...

	def delete_model(self, model_id: str) -> None:
		"""Remove the cached file for *model_id*."""
		...

	def set_active_model(self, model_id: str) -> None:
		"""Persist *model_id* as the active model for this provider."""
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
	) -> None:
		self.provider_id = provider_id
		self._config = config
		self._provider_class = provider_class
		self._set_model_fn = set_model_fn
		self._get_config_fn = get_config_fn
		self._cached_models: list[ManagedModel] | None = None

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
		"""Fetch models from the cloud provider (cached for dialog lifetime)."""
		if self._cached_models is not None:
			return self._cached_models
		try:
			provider = self._provider_class(config=self._config)
			raw = provider.list_models()
		except Exception:
			return []
		result: list[ManagedModel] = []
		for m in raw:
			result.append(
				ManagedModel(
					id=m.id,
					display_name=m.display_name or m.id,
					state=ModelState.READY,
					capabilities=m.capabilities if m.capabilities else (),
				)
			)
		self._cached_models = result
		return result

	def download_model(
		self,
		model_id: str,
		on_progress: DownloadProgressCallback,
	) -> None:
		raise NotImplementedError("Cloud providers do not support model download")

	def delete_model(self, model_id: str) -> None:
		raise NotImplementedError("Cloud providers do not support model delete")

	def set_active_model(self, model_id: str) -> None:
		self._set_model_fn(model_id)
