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

import threading

from logHandler import log

from ..config.settings import (
	get_litert_model_name,
	get_litert_think,
	set_litert_model_name,
)
from .config import OpenAICompatConfig
from .interfaces import LLMProviderError
from .litert_models import LiteRTModelDef, download_url, lookup_model, recommended_models, resolve_identity
from .model_manager import (
	DownloadProgressCallback,
	ManagedModel,
	ModelManagerProvider,
	ModelState,
	ProviderFeatures,
)
from .runtime.model_download import ModelDownloadService
from .runtime.server import LiteRTServerError, get_litert_supervisor

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
		raw = get_litert_model_name()
		return resolve_identity(raw) if raw else None

	def list_managed_models(self) -> list[ManagedModel]:
		"""Return the full catalog with local download state.

		For models with variants, each variant appears as a separate row
		so the user can choose GPU vs CPU builds.  The canonical
		``model_id`` determined by ``resolve_identity`` is used for
		the enabled/disabled check.
		"""
		svc = self._download_service or ModelDownloadService()
		supervisor = get_litert_supervisor()
		models = recommended_models()

		# Models already imported into the server registry stay visible
		# even after their cached source file is deleted post-import.
		# Import state is model-level (any variant counts).
		imported = {
			model.model_id
			for model in models
			if supervisor.catalog_model_dir(model.model_id) is not None
			and (supervisor.catalog_model_dir(model.model_id) / "model.litertlm").is_file()
		}

		# Collect all known filenames for dedup.
		known_filenames: set[str] = set()
		for m in models:
			known_filenames.update(m.all_filenames)

		# Ensure the default model is enabled on first run so it is
		# immediately usable from the model manager.
		from ..ui.enabled_models import EnabledModelsStore

		enabled_store = EnabledModelsStore()
		if not enabled_store.get_enabled("litert-lm"):
			default = lookup_model(_DEFAULT_MODEL_ID)
			if default is not None:
				enabled_store.set_enabled("litert-lm", default.model_id, True)

		think = bool(self._config.think if self._config is not None else None) or get_litert_think()

		result: list[ManagedModel] = []

		for model in models:
			model_imported = model.model_id in imported
			caps = _capabilities_for(model, think)

			if model.has_variants:
				# ── Emit one row per variant ───────────────────────
				for variant in model.variants:
					vid = variant.filename
					downloaded = svc.is_downloaded(vid) or (
						model_imported and variant is model.variants[0]
					)
					# Variant display: "Model Name — Variant Label"
					display = f"{model.display_name} — {variant.display_label}"
					result.append(
						ManagedModel(
							id=vid,
							display_name=display,
							state=ModelState.DOWNLOADED
							if (downloaded)
							else ModelState.NOT_DOWNLOADED,
							priority=model.priority,
							size_hint=variant.size_hint_human or model.size_hint_human,
							capabilities=caps,
						)
					)
			else:
				# ── Single-file model (no variants) ───────────────
				downloaded = svc.is_downloaded(model.filename) or model_imported
				result.append(
					ManagedModel(
						id=model.model_id,
						display_name=model.display_name,
						state=ModelState.DOWNLOADED
						if downloaded
						else ModelState.NOT_DOWNLOADED,
						priority=model.priority,
						size_hint=model.size_hint_human,
						capabilities=caps,
					)
				)

		# Surface locally cached files that are not in the catalog
		# (e.g. models copied in manually).
		if svc.cache_dir.exists():
			for f in sorted(svc.cache_dir.iterdir()):
				if f.suffix == ".litertlm" and f.name not in known_filenames:
					owner = lookup_model(f.name)
					canonical_id = owner.model_id if owner is not None else f.name
					result.append(
						ManagedModel(
							id=canonical_id,
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
		cancel_event: threading.Event | None = None,
	) -> None:
		"""Download *model_id* to the local cache.

		*model_id* may be either a canonical HuggingFace model ID,
		a primary filename, or a variant filename.

		When *model_id* resolves to a model with variants, only the
		matching variant file is downloaded.  When it resolves to a
		model without variants, the primary file is downloaded.

		*cancel_event* (optional) allows the caller to request
		cancellation; the partial file is preserved for future resume.

		Runs in a **background thread** — the caller must dispatch UI
		updates via ``wx.CallAfter`` or equivalent.
		"""
		model = lookup_model(model_id)
		if model is None:
			raise LLMProviderError(f"Unknown model for download: {model_id}")

		# Determine which file to download: variant filename if
		# *model_id* matches a variant, else the primary filename.
		download_filename = model.filename
		for v in model.variants:
			if model_id in (v.filename, v.variant_id):
				download_filename = v.filename
				break

		svc = self._download_service or ModelDownloadService()

		# Bytes progress gives richer status than the text-only callbacks.
		def _on_bytes(downloaded: int, total: int) -> None:
			if total > 0:
				pct = downloaded * 100 // total
				on_progress(
					f"Downloading {download_filename} ({pct}%)",
					downloaded,
					total,
				)
			else:
				mb = downloaded / 1024 / 1024
				on_progress(
					f"Downloading {download_filename} ({mb:.0f} MB)",
					downloaded,
					total,
				)

		svc.download(
			model_name=download_filename,
			url=download_url(model, download_filename),
			on_progress=None,
			on_bytes_progress=_on_bytes,
			cancel_event=cancel_event,
		)

	def delete_model(self, model_id: str) -> None:
		"""Remove the cached model file, if any.

		*model_id* may be either a canonical HuggingFace model ID, a
		primary filename, or a variant filename.  The corresponding
		``.litertlm`` file is resolved and removed from the download
		cache.
		"""
		# Resolve which file to delete.
		model = lookup_model(model_id)
		if model is not None and model.has_variants:
			# *model_id* may be a variant filename — use it directly.
			filename = model_id if model_id in model.all_filenames else model.filename
		else:
			filename = model.filename if model is not None else model_id
		svc = self._download_service or ModelDownloadService()
		path = svc.model_path(filename)
		if path.exists():
			path.unlink()
			log.info("Deleted model: %s", path)
		else:
			log.debug("Model not found for deletion: %s", path)

	def set_active_model(self, model_id: str) -> None:
		"""Persist *model_id* and import the variant file if needed.

		When *model_id* matches a variant filename, the variant file
		is imported into the server's model catalog (replacing the
		previous weights for that model).  The stored active model
		name is always the canonical HuggingFace repo ID.
		"""
		canonical = resolve_identity(model_id)
		set_litert_model_name(canonical)

		# If *model_id* is a variant filename, import that specific
		# file into the server so the user gets the right backend.
		model = lookup_model(model_id)
		if model is None or not model.has_variants:
			return

		# Determine if a variant was targeted.
		download_filename: str | None = None
		if model_id != canonical and model_id in model.all_filenames:
			download_filename = model_id
		else:
			# Pick the recommended variant for this hardware.
			rec = model.recommended_variant()
			if rec is not None:
				download_filename = rec.filename

		if download_filename is None:
			return

		svc = self._download_service or ModelDownloadService()
		if not svc.is_downloaded(download_filename):
			log.warning(
				"Variant %s is not downloaded; skipping import",
				download_filename,
			)
			return

		supervisor = get_litert_supervisor()
		src_path = svc.model_path(download_filename)
		try:
			supervisor.import_model(src_path, canonical)
		except LiteRTServerError as exc:
			raise LLMProviderError(
				f"Failed to import variant {download_filename}: {exc}"
			) from exc

	def get_available_model_ids(self) -> list[str]:
		"""Return canonical model IDs that are downloaded or imported.

		Only models with at least one variant file on disk (or already
		imported into the runtime catalog) are returned.  This is the
		single source of truth for the WebView model dropdown — callers
		must not re-implement readiness checks.
		"""
		models = recommended_models()
		svc = self._download_service or ModelDownloadService()
		supervisor = get_litert_supervisor()

		available: list[str] = []

		for model in models:
			# Check download cache for any variant.
			any_downloaded = False
			if model.has_variants:
				for v in model.variants:
					if svc.is_downloaded(v.filename):
						any_downloaded = True
						break
			elif svc.is_downloaded(model.filename):
				any_downloaded = True

			# Check runtime catalog (model may have been imported,
			# after which the source file is deleted).
			if not any_downloaded:
				catalog_dir = supervisor.catalog_model_dir(model.model_id)
				catalog_file = (
					catalog_dir / "model.litertlm"
					if catalog_dir is not None
					else None
				)
				if catalog_file is not None and catalog_file.is_file():
					any_downloaded = True

			if any_downloaded:
				available.append(model.model_id)

		# Surface locally cached files not in the catalog (e.g.
		# custom .litertlm files copied in manually).
		if svc.cache_dir.exists():
			for f in sorted(svc.cache_dir.iterdir()):
				if f.suffix == ".litertlm":
					owner = lookup_model(f.name)
					canonical_id = owner.model_id if owner is not None else f.name
					if canonical_id not in available:
						available.append(canonical_id)

		return available
