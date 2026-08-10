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
from .litert_models import download_url, effective_capabilities_for, lookup_model, recommended_models, resolve_identity
from .model_manager import (
	DownloadProgressCallback,
	ManagedModel,
	ModelManagerProvider,
	ModelState,
	ProviderFeatures,
)
from .runtime.model_download import ModelDownloadService
from .runtime.server import LiteRTServerError, get_litert_supervisor

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

		think = bool(self._config.think if self._config is not None else None) or get_litert_think()

		result: list[ManagedModel] = []

		for model in models:
			model_imported = model.model_id in imported

			if model.has_variants:
				# ── Emit one row per variant ───────────────────────
				for variant in model.variants:
					vid = variant.filename
					downloaded = svc.is_downloaded(vid) or (
						model_imported and variant is model.variants[0]
					)
					caps = effective_capabilities_for(model, variant, think)
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
							description=model.description,
							canonical_id=model.model_id,
						)
					)
			else:
				# ── Single-file model (no variants) ───────────────
				downloaded = svc.is_downloaded(model.filename) or model_imported
				caps = effective_capabilities_for(model, think=think)
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
						description=model.description,
					)
				)

		# Surface locally cached files that are not in the catalog
		# (e.g. models copied in manually).
		if svc.cache_dir.exists():
			for f in sorted(svc.cache_dir.iterdir()):
				if f.suffix == ".litertlm" and f.name not in known_filenames:
					owner = lookup_model(f.name)
					canonical_id = owner.model_id if owner is not None else f.name
					caps = effective_capabilities_for(owner, think=think) if owner is not None else ("completion", "chat", "streaming", "text_input", "text_output")
					result.append(
						ManagedModel(
							id=canonical_id,
							display_name=f.stem,
							state=ModelState.DOWNLOADED,
							priority=100,
							capabilities=caps,
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
		"""Unregister *model_id* from LiteRT-LM and remove the cache file.

		*model_id* may be either a canonical HuggingFace model ID, a
		primary filename, or a variant filename.

		The LiteRT-LM catalog is unregistered first (via the ``litert-lm
		delete`` CLI).  The download-cache artifact is only removed
		**after** successful unregistration so that a failed unregister
		does not orphan a model that is still in the catalog.
		"""
		canonical = resolve_identity(model_id)
		model = lookup_model(model_id)

		# Resolve the cache filename (variant-aware).
		if model is not None and model.has_variants:
			filename = model_id if model_id in model.all_filenames else model.filename
		else:
			filename = model.filename if model is not None else model_id

		# ── Step 1: Unregister from LiteRT-LM catalog ───────────
		supervisor = get_litert_supervisor()
		catalog_dir = supervisor.catalog_model_dir(canonical)
		if catalog_dir is not None and catalog_dir.is_dir():
			supervisor.delete_model(canonical)

		# ── Step 2: Remove download-cache artifact ──────────────
		svc = self._download_service or ModelDownloadService()
		path = svc.model_path(filename)
		if path.exists():
			path.unlink()
			log.info("Deleted model from cache: %s", path)
		else:
			log.debug("Model not found in download cache: %s", path)

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

	def resolve_model_identity(self, model_id: str) -> str:
		"""Resolve *model_id* to its canonical HuggingFace repo ID.

		Variant filenames and loose canonical IDs are all normalised
		through ``resolve_identity`` so the persisted model name is
		always the authoritative repo identifier.
		"""
		return resolve_identity(model_id)
