# -*- coding: utf-8 -*-
"""LiteRT-LM model manager.

The friendly_name is the universal model identity — stored in config,
sent to the server as the model ID, used in the UI, and matched against
``/v1/models``.  No derived or compound IDs anywhere.
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
from .model_import import ModelImportRequest, ModelImportError, ModelSourceKind, parse_model_import_source
from .litert_models import (
	download_url,
	effective_capabilities_for,
	lookup_by_friendly_name,
	recommended_models,
	resolve_identity,
)
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
		return ProviderFeatures(download=True, delete=True, import_model=True)

	@property
	def active_model_id(self) -> str | None:
		"""The stored friendly_name of the active model."""
		return get_litert_model_name() or None

	def list_managed_models(self) -> list[ManagedModel]:
		"""Build the model list from server /v1/models and catalog.

		Each row is identified by its friendly_name which matches the
		server registration ID exactly.
		"""
		svc = self._download_service or ModelDownloadService()
		supervisor = get_litert_supervisor()
		models = recommended_models()
		think = bool(self._config.think if self._config is not None else None) or get_litert_think()
		server_ids_lower: set[str] = {s.lower() for s in supervisor.list_server_models()}

		result: list[ManagedModel] = []

		for model in models:
			if model.has_variants:
				for variant in model.variants:
					fn = variant.friendly_name
					registered = fn.lower() in server_ids_lower
					in_cache = svc.is_downloaded(variant.filename)
					caps = effective_capabilities_for(model, variant, think)
					display = f"{model.display_name} — {variant.display_label}"
					result.append(ManagedModel(
						id=fn,
						display_name=display,
						state=ModelState.DOWNLOADED if (registered or in_cache) else ModelState.NOT_DOWNLOADED,
						priority=model.priority,
						size_hint=variant.size_hint_human or model.size_hint_human,
						capabilities=caps,
						description=model.description,
						canonical_id=model.friendly_name,
					))
			else:
				fn = model.friendly_name
				registered = fn.lower() in server_ids_lower
				in_cache = svc.is_downloaded(model.filename)
				caps = effective_capabilities_for(model, think=think)
				result.append(ManagedModel(
					id=fn,
					display_name=model.display_name,
					state=ModelState.DOWNLOADED if (registered or in_cache) else ModelState.NOT_DOWNLOADED,
					priority=model.priority,
					size_hint=model.size_hint_human,
					capabilities=caps,
					description=model.description,
				))

		# Surface server-registered models not in the static catalog.
		known_ids: set[str] = {m.id.lower() for m in result}
		for server_id in supervisor.list_server_models():
			if server_id.lower() in known_ids:
				continue
			parsed = lookup_by_friendly_name(server_id)
			if parsed is not None:
				model_def, variant = parsed
				caps = effective_capabilities_for(model_def, variant, think)
				fn = variant.friendly_name if variant else model_def.friendly_name
				display = f"{model_def.display_name} — {variant.display_label}" if variant else model_def.display_name
				result.append(ManagedModel(
					id=fn,
					display_name=display,
					state=ModelState.DOWNLOADED,
					priority=model_def.priority,
					size_hint=variant.size_hint_human if variant else model_def.size_hint_human,
					capabilities=caps,
					description=model_def.description,
					canonical_id=model_def.friendly_name if variant else None,
				))
			else:
				result.append(ManagedModel(
					id=server_id,
					display_name=server_id,
					state=ModelState.DOWNLOADED,
					priority=100,
					capabilities=("completion", "chat", "streaming", "text_input", "text_output"),
				))

		return result

	# ------------------------------------------------------------------
	# Download
	# ------------------------------------------------------------------

	def download_model(
		self,
		model_id: str,
		on_progress: DownloadProgressCallback,
		cancel_event: threading.Event | None = None,
	) -> None:
		"""Download and register the model.

		*model_id* is a friendly_name.  The HF file is downloaded,
		then imported into the server under the same friendly_name.
		"""
		parsed = lookup_by_friendly_name(model_id)
		if parsed is None:
			raise LLMProviderError(f"Unknown model: {model_id}")

		model_def, variant = parsed
		if variant is not None:
			fn = variant.friendly_name
			dl_filename = variant.filename
		else:
			fn = model_def.friendly_name
			dl_filename = model_def.filename

		svc = self._download_service or ModelDownloadService()

		def _on_bytes(downloaded: int, total: int) -> None:
			if total > 0:
				pct = downloaded * 100 // total
				on_progress(f"Downloading {dl_filename} ({pct}%)", downloaded, total)
			else:
				mb = downloaded / 1024 / 1024
				on_progress(f"Downloading {dl_filename} ({mb:.0f} MB)", downloaded, total)

		svc.download(
			model_name=dl_filename,
			url=download_url(model_def, dl_filename),
			on_progress=None,
			on_bytes_progress=_on_bytes,
			cancel_event=cancel_event,
		)

		# Auto-register under the friendly_name.
		supervisor = get_litert_supervisor()
		try:
			supervisor.import_model(svc.model_path(dl_filename), fn)
			log.info("Registered %s as %s", dl_filename, fn)
		except LiteRTServerError as exc:
			log.warning("Could not register %s: %s", dl_filename, exc)

	def import_model(
		self,
		request: ModelImportRequest,
		on_progress: DownloadProgressCallback,
		cancel_event: threading.Event | None = None,
	) -> None:
		"""Import a local LiteRT artifact or HF repository artifact.

		GGUF is intentionally rejected here: it belongs to a llama.cpp-style
		provider, while this adapter only registers LiteRT artifacts. The same
		request contract can be implemented by that future provider.
		"""
		try:
			parsed = parse_model_import_source(request.source, request.model_id, self.provider_id)
		except ModelImportError as exc:
			raise LLMProviderError(str(exc)) from exc
		if parsed.file_suffix == ".gguf":
			raise LLMProviderError("GGUF files require a llama.cpp-compatible provider")

		# LiteRT-LM owns Hugging Face repository resolution and its registry.
		# Do not duplicate that logic with a generic "first .litertlm" download.
		if parsed.kind is ModelSourceKind.HUGGING_FACE:
			if not parsed.artifact:
				raise LLMProviderError(
					"LiteRT Hugging Face imports require an explicit artifact: "
					"repo#file=model.litertlm"
				)
			supervisor = get_litert_supervisor()
			try:
				supervisor.import_huggingface_model(
					parsed.source,
					parsed.artifact,
					parsed.model_id,
					on_progress=lambda message: on_progress(message, None, None),
				)
			except LiteRTServerError as exc:
				raise LLMProviderError(str(exc)) from exc
			return

		svc = self._download_service or ModelDownloadService()
		cache_name = f"{parsed.model_id}{parsed.file_suffix or '.litertlm'}"
		if parsed.kind is ModelSourceKind.LOCAL_FILE:
			try:
				model_path = svc.stage_local_file(parsed.source, cache_name)
			except Exception as exc:
				raise LLMProviderError(f"Could not stage model file: {exc}") from exc
			delete_source = False
		else:
			raise LLMProviderError("Unsupported LiteRT import source")

		supervisor = get_litert_supervisor()
		try:
			supervisor.import_model(
				model_path,
				parsed.model_id,
				on_progress=lambda message: on_progress(message, None, None),
				delete_source=delete_source,
			)
		except LiteRTServerError as exc:
			raise LLMProviderError(str(exc)) from exc

	# ------------------------------------------------------------------
	# Delete
	# ------------------------------------------------------------------

	def delete_model(self, model_id: str) -> None:
		"""Delete all registered variants of this model and remove cache."""
		parsed = lookup_by_friendly_name(model_id)
		if parsed is None:
			raise LLMProviderError(f"Unknown model: {model_id}")

		model_def, _ = parsed
		supervisor = get_litert_supervisor()
		svc = self._download_service or ModelDownloadService()

		# Collect all friendly_names belonging to this model.
		sibling_fns: set[str] = {model_def.friendly_name}
		for v in model_def.variants:
			sibling_fns.add(v.friendly_name)

		# Unregister any server IDs matching our friendly_names.
		for server_id in supervisor.list_server_models():
			resolved = resolve_identity(server_id)
			if resolved in sibling_fns:
				try:
					supervisor.delete_model(server_id)
				except LiteRTServerError as exc:
					log.warning("Failed to unregister %s: %s", server_id, exc)

		# Remove cache files for all variants.
		for v in model_def.variants:
			path = svc.model_path(v.filename)
			if path.exists():
				path.unlink()
				log.info("Deleted cache: %s", path)
		path = svc.model_path(model_def.filename)
		if path.exists():
			path.unlink()
			log.info("Deleted cache: %s", path)

	# ------------------------------------------------------------------
	# Activate
	# ------------------------------------------------------------------

	def set_active_model(self, model_id: str) -> None:
		"""Import if needed, then persist the friendly_name.

		If the model is already registered under friendly_name on the
		server, just persist it.  If it's registered under a legacy
		ID, rename.  If only a cache file exists, import it.
		"""
		parsed = lookup_by_friendly_name(model_id)
		if parsed is None:
			set_litert_model_name(model_id)
			return

		model_def, variant = parsed
		fn = variant.friendly_name if variant else model_def.friendly_name
		dl_filename = variant.filename if variant else model_def.filename
		supervisor = get_litert_supervisor()
		server_ids_lower = {s.lower() for s in supervisor.list_server_models()}

		# Already registered under the right name.
		if fn.lower() in server_ids_lower:
			set_litert_model_name(fn)
			return

		# Try renaming any legacy server ID to friendly_name.
		for server_id in supervisor.list_server_models():
			if resolve_identity(server_id) == fn:
				try:
					supervisor.rename_model(server_id, fn)
					set_litert_model_name(fn)
				except LiteRTServerError as exc:
					log.warning("Could not rename %s → %s: %s", server_id, fn, exc)
				return

		# Import from cache.
		svc = self._download_service or ModelDownloadService()
		if not svc.is_downloaded(dl_filename):
			log.warning("%s not in cache; download first", dl_filename)
			return
		supervisor.import_model(svc.model_path(dl_filename), fn)
		set_litert_model_name(fn)

	# ------------------------------------------------------------------
	# Available model IDs (WebView dropdown)
	# ------------------------------------------------------------------

	def get_available_model_ids(self) -> list[str]:
		"""Return friendly_names for all registered or downloaded models."""
		models = recommended_models()
		svc = self._download_service or ModelDownloadService()
		supervisor = get_litert_supervisor()
		server_ids_lower = {s.lower() for s in supervisor.list_server_models()}

		available: list[str] = []
		for model in models:
			if model.has_variants:
				for variant in model.variants:
					fn = variant.friendly_name
					if fn.lower() in server_ids_lower or svc.is_downloaded(variant.filename):
						available.append(fn)
			else:
				fn = model.friendly_name
				if fn.lower() in server_ids_lower or svc.is_downloaded(model.filename):
					available.append(fn)
		return available

	def resolve_model_identity(self, model_id: str) -> str:
		"""Resolve *model_id* to a friendly_name."""
		return resolve_identity(model_id)
