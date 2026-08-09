# -*- coding: utf-8 -*-
"""LiteRT-LM model manager — browse, download, delete, activate local models.

Implements the ``ModelManagerProvider`` protocol for the LiteRT-LM
provider so the model manager dialog can manage local ``.litertlm``
model files: browse the catalog with download state, download from
Hugging Face with progress, delete cached files, and set the active
model.

This is the local counterpart of ``CloudModelManagerAdapter`` (which
covers cloud providers).  It does **not** implement ``LLMProvider`` —
inference is handled by ``OpenAICompatProvider``; this class only
owns the model catalog and the on-disk cache.
"""

from __future__ import annotations

from logHandler import log

from ..config.settings import (
	get_litert_model_name,
	get_litert_think,
	set_litert_model_name,
)
from .config import OpenAICompatConfig
from .interfaces import LLMProviderError
from .litert_models import LiteRTModelDef, download_url, lookup_model, recommended_models
from .model_manager import (
	DownloadProgressCallback,
	ManagedModel,
	ModelManagerProvider,
	ModelState,
	ProviderFeatures,
)
from .runtime.model_download import ModelDownloadService
from .runtime.server import get_litert_supervisor

#: Repo ID of the default model, enabled automatically on first run.
_DEFAULT_MODEL_ID = "litert-community/gemma-4-E2B-it-litert-lm"

_TEXT_CAPABILITIES = ("completion", "chat", "streaming", "text_input", "text_output")


def _capabilities_for(model: LiteRTModelDef, think: bool) -> tuple[str, ...]:
	"""Return a capabilities tuple for a model definition."""
	caps = list(_TEXT_CAPABILITIES)
	if model.vision:
		caps.extend(("vision", "image_input"))
	if think and model.thinking:
		caps.append("thinking")
	return tuple(caps)


class LiteRTModelManager(ModelManagerProvider):
	"""Model manager for LiteRT-LM local models."""

	provider_id = "litert-lm"

	def __init__(
		self,
		config: OpenAICompatConfig | None = None,
		download_service: ModelDownloadService | None = None,
	) -> None:
		self._config = config
		self._download_service = download_service

	# ------------------------------------------------------------------
	# ModelManagerProvider protocol
	# ------------------------------------------------------------------

	@property
	def features(self) -> ProviderFeatures:
		return ProviderFeatures(download=True, delete=True)

	@property
	def active_model_id(self) -> str | None:
		return get_litert_model_name() or None

	def list_managed_models(self) -> list[ManagedModel]:
		"""Return the full catalog with local download state."""
		svc = self._download_service or ModelDownloadService()
		supervisor = get_litert_supervisor()
		models = recommended_models()

		# Models already imported into the server registry stay visible
		# even after their cached source file is deleted post-import.
		imported = {
			model.model_id
			for model in models
			if supervisor.catalog_model_dir(model.model_id) is not None
			and (supervisor.catalog_model_dir(model.model_id) / "model.litertlm").is_file()
		}

		# Ensure the default model is enabled on first run so it is
		# immediately usable from the model manager.
		from ..ui.enabled_models import EnabledModelsStore

		enabled_store = EnabledModelsStore()
		if not enabled_store.get_enabled("litert-lm"):
			default = lookup_model(_DEFAULT_MODEL_ID)
			if default is not None:
				enabled_store.set_enabled("litert-lm", default.filename, True)

		think = bool(self._config.think if self._config is not None else None) or get_litert_think()

		catalog_names = {m.filename for m in models}
		result: list[ManagedModel] = []

		for model in models:
			downloaded = svc.is_downloaded(model.filename) or model.model_id in imported
			result.append(
				ManagedModel(
					id=model.filename,
					display_name=model.display_name,
					state=ModelState.DOWNLOADED if downloaded else ModelState.NOT_DOWNLOADED,
					priority=model.priority,
					size_hint=model.size_hint_human,
					capabilities=_capabilities_for(model, think),
				)
			)

		# Surface locally cached files that are not in the catalog
		# (e.g. models copied in manually).
		if svc.cache_dir.exists():
			for f in sorted(svc.cache_dir.iterdir()):
				if f.suffix == ".litertlm" and f.name not in catalog_names:
					result.append(
						ManagedModel(
							id=f.name,
							display_name=f.stem,
							state=ModelState.DOWNLOADED,
							priority=100,
							capabilities=_TEXT_CAPABILITIES,
						)
					)

		return result

	def download_model(
		self,
		model_id: str,
		on_progress: DownloadProgressCallback,
	) -> None:
		"""Download *model_id* to the local cache.

		Runs in a **background thread** — the caller must dispatch UI
		updates via ``wx.CallAfter`` or equivalent.
		"""
		model = lookup_model(model_id)
		if model is None:
			raise LLMProviderError(f"Unknown model for download: {model_id}")
		svc = self._download_service or ModelDownloadService()

		# Bytes progress gives richer status than the text-only callbacks.
		def _on_bytes(downloaded: int, total: int) -> None:
			if total > 0:
				pct = downloaded * 100 // total
				on_progress(
					f"Downloading {model.filename} ({pct}%)",
					downloaded,
					total,
				)
			else:
				mb = downloaded / 1024 / 1024
				on_progress(
					f"Downloading {model.filename} ({mb:.0f} MB)",
					downloaded,
					total,
				)

		svc.download(
			model_name=model.filename,
			url=download_url(model),
			on_progress=None,
			on_bytes_progress=_on_bytes,
		)

	def delete_model(self, model_id: str) -> None:
		"""Remove the cached model file, if any."""
		svc = self._download_service or ModelDownloadService()
		path = svc.model_path(model_id)
		if path.exists():
			path.unlink()
			log.info("Deleted model: %s", path)
		else:
			log.debug("Model not found for deletion: %s", path)

	def set_active_model(self, model_id: str) -> None:
		"""Persist *model_id* as the active LiteRT-LM model."""
		set_litert_model_name(model_id)
