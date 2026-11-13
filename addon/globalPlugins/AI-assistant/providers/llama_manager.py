# -*- coding: utf-8 -*-
"""Model management for the llama.cpp server provider."""

from __future__ import annotations

from dataclasses import asdict, replace
from functools import wraps

import logging
import hashlib
import json
import threading
import urllib.parse
from pathlib import Path
from typing import Any

from ..core.translation import _
from ..core.cancellation import cancellation_event_scope, check_cancelled, RequestCancelled
from .interfaces import LLMProviderError, DownloadCancelledError
from .model_import import (
	ModelImportRequest,
	ModelSourceKind,
	parse_model_import_source,
)
from .model_manager import (
	DownloadProgressCallback,
	ManagedModel,
	ModelAction,
	ModelManagerProvider,
	ProviderFeatures,
)
from .runtime.llama_server import (
	LlamaServerSupervisor,
	LlamaServerError,
	default_llama_server_executable,
	get_llama_supervisor,
)
from .runtime.llama_models import LlamaModelCatalog, LlamaModelRecord, PresetImportPreview, parse_models_preset
from ..core.llama_preset import LlamaPresetCodec
from ..core.llama_options import canonical_key, SOURCE_KEYS, OPTION_BY_KEY
from .llama_catalog import reconcile_llama_entries, selectable_llama_entries
from ..core.model_assets import ModelAssetSnapshot, ModelDiscoverySnapshot

log = logging.getLogger(__name__)


def _serialized(method):
	@wraps(method)
	def wrapped(self, *args, **kwargs):
		with self._lock:
			with self._catalog.lock:
				check_cancelled()
				if method.__name__ in {"import_model", "import_preset", "commit_preset_import", "create_configuration", "create_configuration_from_asset", "duplicate_configuration", "relocate_configuration", "set_runtime_options", "update_configuration", "delete_model", "delete_cached_files"}:
					self._assert_mutable()
				return method(self, *args, **kwargs)
	return wrapped


class LlamaCppModelManager(ModelManagerProvider):
	"""Owns imported GGUF references and the llama-server process."""

	provider_id = "llama-cpp-server"
	_operation_locks = {}
	_operation_locks_guard = threading.Lock()

	def __init__(
		self,
		config: object | None = None,
		*,
		supervisor: LlamaServerSupervisor | None = None,
		cache_dir: str | Path | None = None,
		worker_client: Any | None = None,
		set_model_fn=None,
		clear_model_fn=None,
		get_config_fn=None,
		set_preset_fn=None,
	) -> None:
		self._assets = ()
		self._asset_generation = 0
		self._config = config
		self._worker_client = worker_client
		self._set_model_fn = set_model_fn
		self._clear_model_fn = clear_model_fn
		self._get_config_fn = get_config_fn
		self._set_preset_fn = set_preset_fn
		self._catalog = LlamaModelCatalog(
			cache_dir,
			preset_path=str(getattr(config, "models_preset", "") or "").strip() or None,
		)
		if supervisor is not None:
			self._supervisor = supervisor
		else:
			host, port = self._server_address(config)
			self._supervisor = get_llama_supervisor(
				executable=(
					str(getattr(config, "server_executable", "") or "").strip()
					or default_llama_server_executable()
				),
				host=host,
				port=port,
				worker_client=worker_client,
			)
		with self._operation_locks_guard:
			self._lock = self._operation_locks.setdefault(self._server_address(config), threading.RLock())

	@property
	def features(self) -> ProviderFeatures:
		return ProviderFeatures(download=False, delete=True, import_model=True, import_preset=True, configuration_management=True)

	@property
	def model_operations(self):
		from ..service.llama_operations import get_model_operations
		return get_model_operations((str(self._catalog.cache_directory.parent), self._server_address(self._config)),
			load=self.load_model, unload=self.unload_model)

	def _assert_mutable(self):
		if self.model_operations.active():
			raise ValueError(_("A model operation is running. Stop it or wait before changing configurations or files."))

	def resolve_hf(self, repo, *, role="primary", revision="main"):
		parsed = parse_model_import_source(str(repo).split("#", 1)[0], "artifact-preview", self.provider_id)
		if parsed.is_local_file:
			raise ValueError(_("Enter a Hugging Face repository reference."))
		return self._asset_command("llama_resolve_hf", repo=parsed.source, role=role,
			revision=parsed.revision if parsed.revision != "main" else revision)

	def verify_asset(self, token, *, role="primary"):
		return self._asset_command("llama_verify_asset", token=token, role=role)

	@property
	def active_model_id(self) -> str | None:
		config = self._get_config_fn() if self._get_config_fn else self._config
		value = getattr(config, "model_name", "") if config else ""
		return str(value or "").strip() or None

	@property
	def default_context(self) -> int:
		return int(getattr(self._config, "num_ctx", 0) or 0)

	def _invalidate_caches(self) -> None:
		try:
			from ..service.model_cache import model_catalog_cache, model_capability_cache
			model_catalog_cache.invalidate(self.provider_id)
			model_capability_cache.invalidate(self.provider_id)
		except Exception:
			pass

	@_serialized
	def list_model_entries(self):
		entries = reconcile_llama_entries(self._catalog.list_records(), self._assets, self.list_server_models(refresh=True),
			endpoint_owned=bool(self._supervisor.is_running and not self._supervisor.is_adopted), stale=bool(self.server_models_error))
		for index, entry in enumerate(entries):
			if entry.kind == "configuration":
				record = self._catalog.find_exact(entry.model.id)
				path = self._owned_cache_path(record)
				if path is not None and path.is_file():
					entries[index] = replace(entry, model=replace(entry.model,
						actions=(*entry.model.actions, ModelAction.DELETE_CACHE), cached_files=(str(path),)))
		return entries

	def list_managed_models(self) -> list[ManagedModel]:
		return [entry.model for entry in self.list_model_entries() if entry.kind != "downloaded"]

	def _asset_command(self, command, **payload):
		client = self._worker_client or self._supervisor._get_worker_client(start=True)
		if client is None:
			raise LLMProviderError(_("The local AI worker is unavailable."))
		response = client.send_command({"type": command, "command": command, **payload}, timeout=30.0)
		if not response.get("success"):
			raise LLMProviderError(response.get("error_message") or _("Unable to inspect downloaded models."))
		return response["result"]

	def discover_assets(self, roots=None) -> ModelDiscoverySnapshot:
		from ..config.settings import get_llama_cache_roots
		with self._lock:
			self._asset_generation += 1
			generation = self._asset_generation
		snapshot = ModelDiscoverySnapshot.from_dict(self._asset_command("llama_discover_assets",
			roots=get_llama_cache_roots() if roots is None else roots, generation=generation))
		with self._lock:
			if snapshot.generation == self._asset_generation:
				# A failed root is not a successful empty scan. Retain its rows,
				# but discard verification tokens and Create eligibility.
				current_ids = {asset.asset_id for asset in snapshot.assets}
				failed_roots = [Path(root).resolve() for root in snapshot.errors]
				retained = tuple(replace(asset, availability="unknown", token="") for asset in self._assets
					if asset.asset_id not in current_ids and any(Path(asset.path).resolve().is_relative_to(root) for root in failed_roots))
				snapshot = replace(snapshot, assets=(*snapshot.assets, *retained))
				self._assets = snapshot.assets
		return snapshot

	@_serialized
	def create_configuration_from_asset(self, token, model_id, display_name, options, *, select=False, companions=()):
		if self._catalog.find_exact(model_id) is not None:
			raise ValueError(_("This configuration ID already exists. Choose another ID."))
		asset = ModelAssetSnapshot.from_dict(self._asset_command("llama_verify_asset", token=token))
		if asset.availability != "present":
			raise ValueError(_("This asset is incomplete or unsupported."))
		check_cancelled()
		self._validate_display_name(display_name)
		companions = self._validated_companions(companions)
		record = LlamaModelRecord(model_id, asset.path, "local_file", local_path=asset.path,
			display_name=display_name.strip(), asset_id=asset.asset_id, preset_options=dict(options), ownership="user", companions=companions,
			asset_source=asset.source, asset_repository=asset.repository, asset_revision=asset.revision, asset_artifact=asset.artifact)
		self._catalog.upsert(record)
		self._invalidate_caches()
		if select:
			self.set_active_model(model_id)
		return model_id

	def _validated_companions(self, companions):
		from ..core.llama_companions import validate_companions
		validated = []
		for entry in companions or ():
			value = dict(entry)
			if value.get("asset_token"):
				asset = self.verify_asset(value.pop("asset_token"), role=value["role"])
				value.update(kind="local_file", source=asset["path"], local_path=asset["path"])
			value["ownership"] = "user"
			value["compatibility"] = "unverified"
			for key in ("file_identity", "resolved_revision"):
				value.pop(key, None)
			if value.get("kind") == "hugging_face":
				value.pop("local_path", None)
			validated.append(value)
		values = validate_companions(validated)
		for companion in values:
			if companion["kind"] == "local_file":
				path = Path(companion["local_path"]).expanduser().resolve()
				if not path.is_file():
					raise ValueError(_("Companion file is missing: {file}. Locate it or remove the companion.").format(file=path))
				companion.update(source=str(path), local_path=str(path))
		return values

	@staticmethod
	def _validate_display_name(name):
		if not str(name).strip() or any(ord(char) < 32 for char in str(name)):
			raise ValueError(_("Configuration name must be a nonempty single-line name."))

	@property
	def server_models_error(self) -> str | None:
		error = getattr(self._supervisor, "models_error", None)
		return error if isinstance(error, str) else None

	def list_server_models(self, *, refresh: bool = False) -> tuple[dict[str, object], ...]:
		"""Return the cached authoritative llama-server model catalog."""
		removed = {identity.casefold() for identity in self._catalog.removed_identities()}
		registered_ids = {record.model_id for record in self._catalog.list_records()}
		return tuple(item for item in self._supervisor.list_models(refresh=refresh) if str(item.get("id", "")) in registered_ids or str(item.get("id", "")).casefold() not in removed)

	@_serialized
	def import_model(
		self,
		request: ModelImportRequest,
		on_progress: DownloadProgressCallback,
		cancel_event: threading.Event | None = None,
		*,
		display_name: str = "",
		companions=(),
		preset_options=None,
	) -> None:
		if cancel_event is not None and cancel_event.is_set():
			return
		try:
			parsed = parse_model_import_source(
				request.source,
				request.model_id,
				self.provider_id,
			)
			if parsed.kind is ModelSourceKind.HUGGING_FACE:
				parsed = replace(parsed, revision=request.revision if request.revision != "main" else parsed.revision, artifact=request.artifact or parsed.artifact, variant=request.variant or parsed.variant)
		except ValueError as exc:
			raise LLMProviderError(str(exc)) from exc
		if parsed.kind is ModelSourceKind.HUGGING_FACE and parsed.revision != "main":
			raise LLMProviderError(_("llama.cpp imports currently support the main Hugging Face revision only."))
		if parsed.artifact and (Path(parsed.artifact).suffix.lower() != ".gguf" or any(char in parsed.artifact for char in "\\\x00\r\n") or ".." in Path(parsed.artifact).parts):
			raise LLMProviderError(_("Select a valid GGUF artifact using repo#file=model.gguf."))
		if parsed.kind is ModelSourceKind.LOCAL_FILE and parsed.file_suffix != ".gguf":
			raise LLMProviderError(_("llama-server imports require a .gguf file or Hugging Face GGUF repository"))
		local_path: str | None = None
		if parsed.kind is ModelSourceKind.LOCAL_FILE:
			local_path = str(Path(parsed.source).resolve())
			on_progress(_("Registering local GGUF model"), None, None)
		else:
			on_progress(_("Registering Hugging Face GGUF variant"), None, None)
		record = LlamaModelRecord(
			model_id=parsed.model_id,
			display_name=display_name,
			companions=self._validated_companions(companions),
			preset_options=dict(preset_options or {}),
			source=parsed.source,
			kind=parsed.kind.value,
			revision=parsed.revision,
			artifact=parsed.artifact,
			variant=parsed.variant,
			local_path=local_path,
		)
		check_cancelled()
		if cancel_event is not None and cancel_event.is_set():
			raise DownloadCancelledError(_("Model import cancelled."))
		self._catalog.upsert(record)
		self._invalidate_caches()
		on_progress(_("Model {model_id} is registered and will load on first use").format(model_id=record.model_id), None, None)

	@_serialized
	def import_preset(self, path: str | Path):
		"""Import supported settings once into the authoritative catalog."""
		check_cancelled()
		summary = self._catalog.import_preset(path)
		self._invalidate_caches()
		return summary

	def _catalog_digest(self):
		return hashlib.sha256(json.dumps([asdict(record) for record in self._catalog.list_records()], sort_keys=True).encode()).hexdigest()

	@_serialized
	def preview_preset_import(self, path: str) -> PresetImportPreview:
		source = Path(path).resolve()
		content = source.read_bytes()
		text = content.decode("utf-8-sig")
		LlamaPresetCodec().validate(text)
		section, unsupported = "", []
		for raw in text.splitlines():
			line = raw.strip()
			if line.startswith("["):
				section = line[1:-1]
			elif section and "=" in line and not line.startswith(("#", ";")):
				key = canonical_key(line.split("=", 1)[0].strip())
				if key not in SOURCE_KEYS and key not in OPTION_BY_KEY:
					unsupported.append(f"[{section}] {key}")
		records = () if unsupported else parse_models_preset(text, base_directory=source.parent, strict=True)
		if not records and not unsupported:
			raise ValueError(_("The preset contains no importable models."))
		existing = {record.model_id for record in self._catalog.list_records()}
		return PresetImportPreview(str(source), hashlib.sha256(content).hexdigest(), records,
			tuple(sorted(record.model_id for record in records if record.model_id in existing)),
			tuple(sorted(set(unsupported))), self._catalog_digest())

	@_serialized
	def commit_preset_import(self, preview: PresetImportPreview, *, replace_ids: tuple[str, ...]):
		if preview.unsupported:
			raise ValueError(_("Unsupported preset options: {options}.").format(options=", ".join(preview.unsupported)))
		if not set(preview.replace_ids).issubset(replace_ids):
			raise ValueError(_("Replace must be confirmed for existing configuration IDs."))
		if hashlib.sha256(Path(preview.source).read_bytes()).hexdigest() != preview.digest or self._catalog_digest() != preview.catalog_digest:
			raise ValueError(_("The preset or model settings changed. Preview the import again."))
		check_cancelled()
		summary = self._catalog.import_records(preview.records, source=preview.source)
		self._invalidate_caches()
		return summary

	@_serialized
	def create_configuration(self, source: str, model_id: str, display_name: str, *, select=False, companions=(), options=None):
		self._validate_display_name(display_name)
		if self._catalog.find_exact(model_id) is not None:
			raise ValueError(_("This configuration ID already exists. Choose another ID."))
		parsed = parse_model_import_source(source, model_id, self.provider_id)
		self.import_model(parsed, lambda *args: None, display_name=display_name.strip(), companions=companions, preset_options=options)
		if select:
			self.set_active_model(model_id)
		return model_id

	@_serialized
	def update_configuration(self, model_id, *, display_name=None, source=None, companions=None):
		record = self._catalog.find_exact(model_id)
		if record is None:
			raise ValueError(_("This configuration is no longer registered."))
		if display_name is not None:
			self._validate_display_name(display_name)
			record = replace(record, display_name=display_name.strip())
		if source is not None and source != record.source:
			parsed = parse_model_import_source(source, model_id, self.provider_id)
			if parsed.revision != "main":
				raise ValueError(_("llama.cpp models currently support the main Hugging Face revision only."))
			record = replace(record, source=parsed.source, kind=parsed.kind.value, revision=parsed.revision,
				artifact=parsed.artifact, variant=parsed.variant, local_path=str(Path(parsed.source).resolve()) if parsed.is_local_file else None,
				cached_path=None, ownership="user", asset_id=None, asset_source="", asset_repository=None, asset_revision=None, asset_artifact=None)
			record = replace(record, companions=tuple({**value, "compatibility": "unverified"} for value in record.companions))
		if companions is not None and tuple(companions) != record.companions:
			record = replace(record, companions=self._validated_companions(companions))
		self._catalog.upsert(record)
		self._invalidate_caches()
		return model_id

	def load_model(self, model_id, on_progress, cancel_event):
		self.prepare_configuration(model_id, on_progress, cancel_event)

	def unload_model(self, model_id, on_progress, cancel_event):
		with cancellation_event_scope(cancel_event), self._lock:
			if self._catalog.find_exact(model_id) is None:
				raise ValueError(_("Unload is available only for a registered managed configuration."))
			client = self._worker_client or self._supervisor._get_worker_client(start=True)
			if client is None:
				raise LLMProviderError(_("The local AI worker is unavailable."))
			response = client.send_command({"type": "llama_unload_model", "command": "llama_unload_model", "model_id": model_id,
				"timeout_seconds": 30, "report_readiness_progress": on_progress is not None}, timeout=35,
				**({"on_progress": on_progress} if on_progress else {}))
			if not response.get("success") or response.get("result", response).get("state") != "unloaded":
				raise LLMProviderError(response.get("error_message") or _("The model did not finish unloading."))
			self._invalidate_caches()

	@_serialized
	def relocate_configuration(self, model_id: str, source: str) -> None:
		previous = self._catalog.find_exact(model_id)
		if previous is None:
			raise ValueError(_("This configuration is no longer registered."))
		parsed = parse_model_import_source(source, model_id, self.provider_id)
		if not parsed.is_local_file or parsed.file_suffix != ".gguf":
			raise ValueError(_("Choose a local GGUF model file."))
		check_cancelled()
		self._catalog.upsert(replace(previous, source=str(Path(parsed.source).resolve()), kind="local_file",
			local_path=str(Path(parsed.source).resolve()), cached_path=None, asset_id=None, ownership="user",
			asset_source="", asset_repository=None, asset_revision=None, asset_artifact=None))
		self._invalidate_caches()

	@_serialized
	def duplicate_configuration(self, model_id: str, new_id: str, display_name: str) -> str:
		self._validate_display_name(display_name)
		if self._catalog.find_exact(new_id) is not None:
			raise ValueError(_("This configuration ID already exists. Choose another ID."))
		record = self._catalog.find_exact(model_id)
		if record is None:
			raise ValueError(_("This configuration is no longer registered."))
		from ..config.model_config import get_model_sampling, set_model_sampling
		sampling = get_model_sampling(self.provider_id, model_id)
		self._catalog.upsert(replace(record, model_id=new_id, display_name=display_name.strip(), preset_options=dict(record.preset_options)))
		try:
			set_model_sampling(self.provider_id, new_id, sampling)
		except Exception:
			self._catalog.remove(new_id)
			raise
		self._invalidate_caches()
		return new_id

	def prepare_configuration(self, model_id: str, on_progress, cancel_event) -> None:
		with cancellation_event_scope(cancel_event):
			record = self._catalog.find_exact(model_id)
			if record is None:
				raise ValueError(_("This configuration is no longer registered."))
			self.ensure_running(record, on_progress=on_progress, cancel_event=cancel_event)
			client = self._worker_client or self._supervisor._get_worker_client(start=True)
			if client is None:
				raise LLMProviderError(_("The local AI worker is unavailable."))
			check_cancelled()
			if on_progress:
				on_progress(_("Loading model. Files may download; use Stop operation to cancel."))
			response = client.send_command({"type": "llama_prepare_model", "command": "llama_prepare_model",
				"model_id": model_id, "timeout_seconds": 300, "report_readiness_progress": on_progress is not None}, timeout=305,
				**({"on_progress": on_progress} if on_progress else {}))
			if not response.get("success") or response.get("state") != "loaded":
				raise LLMProviderError(response.get("error_message") or _("The model did not finish loading."))
			with self._lock, self._catalog.lock:
				current = self._catalog.find_exact(model_id)
				if current and current.companions:
					self._catalog.upsert(replace(current, companions=tuple({**value, "compatibility": "verified"} for value in current.companions)))
			self._invalidate_caches()

	@_serialized
	def get_runtime_options(self, model_id: str) -> dict[str, str]:
		record = self._catalog.find_exact(model_id)
		if record is None:
			raise ValueError(_("Runtime settings are available only for registered models."))
		options = dict(record.preset_options)
		if record.context_window is not None and "ctx-size" not in options:
			options["ctx-size"] = str(record.context_window)
		return options

	@_serialized
	def set_runtime_options(self, model_id: str, options: dict[str, str]) -> None:
		self._catalog.update_options(model_id, options)
		self._invalidate_caches()

	@_serialized
	def get_runtime_configuration(self, model_id: str):
		options = self.get_runtime_options(model_id)
		client = self._worker_client or self._supervisor._get_worker_client(start=True)
		if client is None:
			raise LLMProviderError(_("The local AI worker is unavailable."))
		response = client.send_command({"type": "llama_inspect_options", "command": "llama_inspect_options",
			"executable": self._supervisor.executable}, timeout=10.0)
		if not response.get("success"):
			raise LLMProviderError(response.get("error_message") or _("Unable to check supported runtime settings."))
		return options, set(response.get("options", []))

	def download_model(
		self,
		model_id: str,
		on_progress: DownloadProgressCallback,
		cancel_event: threading.Event | None = None,
	) -> None:
		record = self._find_record(model_id)
		if record is None:
			raise LLMProviderError(_("Unknown llama.cpp model: {model_id}").format(model_id=model_id))
		try:
			self.ensure_running(record, on_progress=lambda message: on_progress(message, None, None), cancel_event=cancel_event)
		finally:
			self._invalidate_caches()

	def ensure_running(self, record, *, on_progress=None, cancel_event=None) -> None:
		try:
			with cancellation_event_scope(cancel_event):
				self._ensure_running(record, on_progress=on_progress)
		except RequestCancelled as exc:
			if cancel_event is not None:
				raise DownloadCancelledError(_("Model loading cancelled.")) from exc
			raise

	@_serialized
	def _ensure_running(
		self,
		record: LlamaModelRecord,
		*,
		on_progress=None,
		cancel_event: threading.Event | None = None,
	) -> None:
		if cancel_event is not None and cancel_event.is_set():
			return
		if record.model_id in self._catalog.removed_identities() and self._catalog.find_exact(record.model_id) is None:
			raise LLMProviderError(_("This model registration has been removed."))
		requested_model = record.model_id
		from ..core.llama_companions import can_reuse_companion
		if getattr(record, "companions", ()) and not all(can_reuse_companion(value) for value in record.companions):
			client = self._worker_client or self._supervisor._get_worker_client(start=True)
			if client is None:
				raise LLMProviderError(_("The local AI worker is unavailable."))
			if on_progress:
				on_progress(_("Checking companion files. Missing remote companions may download."))
			response = client.send_command({"type": "llama_resolve_companions", "command": "llama_resolve_companions",
				"companions": list(record.companions), "report_readiness_progress": on_progress is not None}, timeout=305,
				**({"on_progress": on_progress} if on_progress else {}))
			if not response.get("success"):
				raise LLMProviderError(response.get("error_message") or _("Unable to prepare companion files. Edit or locate the missing companion."))
			check_cancelled()
			resolved = response.get("result", {}).get("companions")
			if resolved is None:
				raise LLMProviderError(_("The worker did not return resolved companion files."))
			from ..core.llama_companions import validate_companions
			record = replace(record, companions=validate_companions(resolved))
			self._catalog.upsert(record)
		default_context = int(getattr(self._config, "num_ctx", 0) or 0)
		preset_path = self._catalog.write_preset(default_context=default_context)
		# Command-line context has higher priority than model preset settings.
		context = 0

		worker_client = self._worker_client or getattr(self._supervisor, "_get_worker_client", lambda: None)()
		if worker_client is not None:
			try:
				records_dicts = [
					{
						"model_id": r.model_id,
						"source": r.source,
						"kind": r.kind,
						"revision": r.revision,
						"artifact": r.artifact,
						"variant": r.variant,
						"local_path": r.local_path,
						"context_window": r.context_window,
						"capabilities": list(r.capabilities),
						"preset_options": dict(r.preset_options),
						"companions": list(getattr(r, "companions", ())),
					}
					for r in self._catalog.export_records(default_context=default_context)
				]
				response = worker_client.send_command(
					{
						"type": "llama_configure_preset",
						"command": "llama_configure_preset",
						"models": records_dicts,
						"default_model": requested_model,
						"preset_path": str(preset_path),
						"executable": self._supervisor.executable,
					},
					timeout=10.0,
				)
				if response.get("type") == "error" or response.get("success") is False:
					raise LlamaServerError(response.get("error_message") or _("Could not configure the llama.cpp model preset."))
			except Exception:
				raise

		if self._supervisor.is_running and not self._supervisor.matches_startup_configuration(
			record.server_model,
			model_id=record.model_id,
			models_preset=preset_path,
			context=context,
		):
			# The endpoint cache key alone is insufficient: context and preset
			# contents bind at process startup and therefore require replacement.
			self._supervisor.stop()
		# Recover a server left behind by a previous NVDA process.  Only adopt
		# it when the requested model is already exposed by that server; a
		# handleless process cannot be safely terminated or reconfigured here.
		if not self._supervisor.is_running and not self._supervisor.is_adopted and self._supervisor.is_healthy():
			if not any(
				record.matches_server_id(str(item.get("id", "")))
				for item in self._supervisor.list_models(refresh=True)
			):
				raise LLMProviderError(
					_("A llama-server is already running with a different model preset. Stop it before switching models.")
				)
			self._supervisor.adopt(requested_model)
			return
		if self._supervisor.is_running or self._supervisor.is_adopted:
			if self._supervisor.is_healthy():
				if any(
					record.matches_server_id(str(item.get("id", "")))
					for item in self._supervisor.list_models(refresh=True)
				):
					# llama-server is a router: model selection is carried by the
					# OpenAI-compatible request, so switching does not restart it.
					if not self._supervisor.is_running:
						self._supervisor.adopt(requested_model)
					return
				raise LLMProviderError(
					_("llama-server does not expose model {model_id} in its API").format(model_id=requested_model)
				)
			else:
				self._supervisor.stop()
		self._supervisor.start(
			record.server_model,
			model_id=record.model_id,
			models_preset=preset_path,
			context=context,
			on_progress=on_progress,
		)
		if not self._supervisor.wait_until_ready(on_progress=on_progress):
			raise LLMProviderError(_("llama-server did not become ready"))

	def _stop_owned_router(self) -> None:
		status = self._supervisor.status(refresh=True, strict=True)
		if status.is_running and not status.is_adopted:
			self._supervisor.stop(strict=True)

	def _owned_cache_path(self, record):
		if record.ownership != "addon" or not record.cached_path:
			return None
		root = self._catalog.cache_directory.resolve()
		path = Path(record.cached_path).resolve()
		if path.is_relative_to(root) and path != root and path.suffix.lower() == ".gguf":
			return path
		return None

	@staticmethod
	def _record_paths(record):
		paths = [record.local_path, record.cached_path]
		if record.kind == "local_file":
			paths.append(record.source)
		paths.extend(record.preset_options.get(key) for key in ("mmproj", "spec-draft-model", "model-draft"))
		for companion in getattr(record, "companions", ()):
			paths.append(companion.get("local_path"))
			if companion.get("kind") == "local_file":
				paths.append(companion.get("source"))
		return {Path(path).resolve() for path in paths if path}

	def file_dependencies(self, path, *, excluding=None):
		target = Path(path).resolve()
		return tuple(record for record in self._catalog.list_records() if record.model_id != excluding and target in self._record_paths(record))

	def _compare_selection(self, expected: str, value: str) -> bool:
		if self._clear_model_fn:
			return bool(self._clear_model_fn(expected, value))
		if (self.active_model_id or "") != expected:
			return False
		if self._set_model_fn:
			self._set_model_fn(value)
		if self._config is not None:
			object.__setattr__(self._config, "model_name", value)
		return True

	@_serialized
	def delete_model(self, model_id: str) -> None:
		"""Remove an exact registration; never infer an import or delete weights."""
		record = self._catalog.find_exact(model_id)
		if record is None:
			if model_id in self._catalog.removed_identities():
				return
			raise LLMProviderError(_("This model is managed by an external server or is not registered."))
		self._stop_owned_router()
		active = self.active_model_id
		records = self._catalog.list_records()
		active_record = next((item for item in records if item.model_id == active), None)
		if active_record is None and active:
			matches = [item for item in records if item.matches_server_id(active)]
			active_record = matches[0] if len(matches) == 1 else None
		was_active = active_record is not None and active_record.model_id == record.model_id
		cleared = was_active and self._compare_selection(active, "")
		try:
			self._catalog.remove(record.model_id)
		except Exception:
			if cleared:
				self._compare_selection("", active)
			raise
		if cleared and self._config is not None and getattr(self._config, "model_name", None) == active:
			object.__setattr__(self._config, "model_name", "")
		self._invalidate_caches()

	@_serialized
	def delete_cached_files(self, model_id: str) -> None:
		record = self._catalog.find_exact(model_id)
		path = self._owned_cache_path(record) if record is not None else None
		if path is None:
			raise LLMProviderError(_("This model has no verified add-on-owned cached files."))
		dependencies = self.file_dependencies(path, excluding=model_id)
		if dependencies:
			raise LLMProviderError(_("These files are used by other configurations: {models}. Remove or change those references first.").format(
				models=", ".join(record.display_name or record.model_id for record in dependencies)))
		self._stop_owned_router()
		client = self._worker_client or self._supervisor._get_worker_client(start=True)
		if client is None:
			raise LLMProviderError(_("The local AI worker is unavailable."))
		response = client.send_command({"type": "llama_delete_cache", "command": "llama_delete_cache",
			"cache_root": str(self._catalog.cache_directory), "path": str(path), "model_id": record.model_id}, timeout=15.0)
		if not response.get("success"):
			raise LLMProviderError(response.get("error_message") or _("Unable to delete cached model files."))
		self._invalidate_caches()

	@_serialized
	def set_active_model(self, model_id: str) -> None:
		if model_id not in {model.id for model in self.list_managed_models() if ModelAction.SELECT in (model.actions or ())}:
			raise LLMProviderError(_("The selected model is not available."))
		if self._set_model_fn:
			self._set_model_fn(model_id)
		if self._config is not None:
			object.__setattr__(self._config, "model_name", model_id)

	def get_available_model_ids(self) -> list[str]:
		return [entry.model.id for entry in selectable_llama_entries(self.list_model_entries())]

	def resolve_model_identity(self, model_id: str) -> str:
		return str(model_id).strip()

	def close(self) -> None:
		# Provider instances are short-lived; application shutdown owns the
		# shared server process.
		return None

	def find_record(self, model_id: str, *, register_missing: bool = True) -> LlamaModelRecord | None:
		"""Return the persisted source identity for an imported model."""
		return self._catalog.find(model_id, register_missing=register_missing)

	def _load_records(self) -> list[LlamaModelRecord]:
		return list(self._catalog.list_records())

	def _remove_record(self, model_id: str) -> None:
		self._catalog.remove(model_id)

	def _find_record(self, model_id: str) -> LlamaModelRecord | None:
		return self._catalog.find(model_id)

	@staticmethod
	def _server_address(config: object | None) -> tuple[str, int]:
		try:
			parsed = urllib.parse.urlparse(str(getattr(config, "base_url", "") or ""))
			if parsed.hostname and parsed.port:
				return parsed.hostname, parsed.port
		except (TypeError, ValueError):
			pass
		return "127.0.0.1", 8080
