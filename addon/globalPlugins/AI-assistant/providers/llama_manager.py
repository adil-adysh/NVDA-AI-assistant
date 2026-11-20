# -*- coding: utf-8 -*-
"""Hugging Face-only llama.cpp presets and the managed router."""
from __future__ import annotations

import logging
import threading
import urllib.parse
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..core.translation import _
from ..core.cancellation import cancellation_event_scope, check_cancelled, RequestCancelled
from .interfaces import LLMProviderError, DownloadCancelledError
from .model_manager import (
	ManagedModel,
	ModelAction,
	ModelFileAvailability,
	ModelManagerProvider,
	ModelOwnership,
	ModelRuntimeState,
	ModelState,
	ProviderFeatures,
)
from .runtime.llama_server import (
	LlamaServerSupervisor,
	LlamaServerError,
	default_llama_server_executable,
	get_llama_supervisor,
)
from .runtime.llama_models import LlamaModelCatalog, LlamaModelRecord

log = logging.getLogger(__name__)


_UNSET = object()


class LlamaCppModelManager(ModelManagerProvider):
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
	) -> None:
		self._config = config
		self._worker_client = worker_client
		self._set_model_fn = set_model_fn
		self._clear_model_fn = clear_model_fn
		self._get_config_fn = get_config_fn
		self._catalog = LlamaModelCatalog(cache_dir)
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
		return ProviderFeatures(configuration_management=True)

	@property
	def model_operations(self):
		from ..service.llama_operations import get_model_operations
		return get_model_operations((str(self._catalog.preset_path.parent), self._server_address(self._config)),
			load=self.load_model, unload=self.unload_model)

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

	def _worker_command(self, command: str, **payload):
		client = self._worker_client or self._supervisor._get_worker_client(start=True)
		if client is None:
			raise LLMProviderError(_("The local AI worker is unavailable."))
		response = client.send_command({"type": command, "command": command, **payload}, timeout=30.0)
		if not response.get("success"):
			raise LLMProviderError(response.get("error_message") or _("Unable to inspect the Hugging Face repository."))
		return response

	def list_presets(self) -> tuple[LlamaModelRecord, ...]:
		return self._catalog.list_records()

	def list_managed_models(self) -> list[ManagedModel]:
		"""Expose presets to the shared script/UI model listing.

		llama-server cache entries are not presets and must never become
		selectable model IDs. The preset ID is the only valid identity.
		"""
		models = []
		for record in self.list_presets():
			models.append(ManagedModel(
				id=record.model_id,
				display_name=record.display_name or record.model_id,
				state=ModelState.REGISTERED,
				capabilities=record.capabilities,
				canonical_id=record.model_id,
				registered=True,
				ownership=ModelOwnership.ADDON,
				file_availability=ModelFileAvailability.REMOTE,
				runtime_state=ModelRuntimeState.UNKNOWN,
				actions=(ModelAction.SELECT,),
			))
		return models

	def list_server_models(self, *, refresh: bool = False) -> tuple[dict[str, object], ...]:
		return tuple(self._supervisor.list_models(refresh=refresh))

	@property
	def server_models_error(self) -> str | None:
		error = getattr(self._supervisor, "models_error", None)
		return error if isinstance(error, str) else None

	def _validate_display_name(self, name: str) -> None:
		if not str(name).strip() or any(ord(char) < 32 for char in str(name)):
			raise ValueError(_("Preset name must be a nonempty single-line name."))

	def create_preset(self, repo: str, model_id: str, display_name: str, *,
			file: str | None = None, draft_repo: str | None = None,
			draft_file: str | None = None, options: dict[str, str] | None = None,
			spec_type_auto: bool = False, select: bool = False) -> str:
		self._validate_display_name(display_name)
		if self._catalog.find_exact(model_id) is not None:
			raise ValueError(_("This preset ID already exists. Choose another ID."))
		record = LlamaModelRecord(model_id, repo, file=file, draft_repo=draft_repo,
			draft_file=draft_file, preset_options=dict(options or {}), display_name=display_name.strip(),
			spec_type_auto=bool(spec_type_auto))
		self._catalog.upsert(record)
		self._invalidate_caches()
		if select:
			self.set_active_model(model_id)
		return model_id

	def update_preset(self, model_id: str, *, repo: str | None = None, file=_UNSET,
			draft_repo=_UNSET, draft_file=_UNSET,
			display_name: str | None = None, options: dict[str, str] | None = None,
			spec_type_auto: bool | None = None) -> str:
		record = self._catalog.find_exact(model_id)
		if record is None:
			raise ValueError(_("This preset is no longer registered."))
		if display_name is not None:
			self._validate_display_name(display_name)
		record = replace(
			record,
			repo=repo if repo is not None else record.repo,
			file=record.file if file is _UNSET else file,
			draft_repo=record.draft_repo if draft_repo is _UNSET else draft_repo,
			draft_file=record.draft_file if draft_file is _UNSET else draft_file,
			display_name=display_name.strip() if display_name is not None else record.display_name,
			preset_options=dict(options) if options is not None else dict(record.preset_options),
			spec_type_auto=record.spec_type_auto if spec_type_auto is None else bool(spec_type_auto),
		)
		self._catalog.upsert(record)
		self._invalidate_caches()
		return model_id

	def duplicate_preset(self, model_id: str, new_id: str, display_name: str) -> str:
		self._validate_display_name(display_name)
		if self._catalog.find_exact(new_id) is not None:
			raise ValueError(_("This preset ID already exists. Choose another ID."))
		record = self._catalog.find_exact(model_id)
		if record is None:
			raise ValueError(_("This preset is no longer registered."))
		self._catalog.upsert(replace(record, model_id=new_id, display_name=display_name.strip()))
		self._invalidate_caches()
		return new_id

	def set_runtime_options(self, model_id: str, options: dict[str, str]) -> None:
		self._catalog.update_options(model_id, options)
		self._invalidate_caches()

	def get_runtime_options(self, model_id: str) -> dict[str, str]:
		record = self._catalog.find_exact(model_id)
		if record is None:
			raise ValueError(_("Runtime settings are available only for registered presets."))
		return dict(record.preset_options)

	def get_runtime_configuration(self, model_id: str):
		options = self.get_runtime_options(model_id)
		response = self._worker_command("llama_inspect_options", executable=self._supervisor.executable)
		return options, set(response.get("options", []))

	def set_active_model(self, model_id: str) -> None:
		if self._catalog.find_exact(model_id) is None:
			raise LLMProviderError(_("The selected preset is not available."))
		if self._set_model_fn:
			self._set_model_fn(model_id)
		if self._config is not None:
			object.__setattr__(self._config, "model_name", model_id)

	def get_available_model_ids(self) -> list[str]:
		return [record.model_id for record in self._catalog.list_records()]

	def resolve_model_identity(self, model_id: str) -> str:
		return str(model_id).strip()

	def find_record(self, model_id: str) -> LlamaModelRecord | None:
		return self._catalog.find(model_id)

	def load_model(self, model_id, on_progress, cancel_event):
		self.prepare_configuration(model_id, on_progress, cancel_event)

	def unload_model(self, model_id, on_progress, cancel_event):
		with cancellation_event_scope(cancel_event), self._lock:
			if self._catalog.find_exact(model_id) is None:
				raise ValueError(_("Unload is available only for a registered managed preset."))
			response = self._worker_command("llama_unload_model", model_id=model_id,
				timeout_seconds=30, report_readiness_progress=on_progress is not None,
				**({"on_progress": on_progress} if on_progress else {}))
			if (response.get("result") or {}).get("state") != "unloaded":
				raise LLMProviderError(_("The model did not finish unloading."))
			self._invalidate_caches()

	def prepare_configuration(self, model_id: str, on_progress, cancel_event) -> None:
		with cancellation_event_scope(cancel_event):
			record = self._catalog.find_exact(model_id)
			if record is None:
				raise ValueError(_("This preset is no longer registered."))
			self.ensure_running(record, on_progress=on_progress, cancel_event=cancel_event)
			check_cancelled()
			if on_progress:
				on_progress(_("Loading model. Files may download; use Stop operation to cancel."))
			response = self._worker_command("llama_prepare_model", model_id=model_id,
				timeout_seconds=300, report_readiness_progress=on_progress is not None,
				**({"on_progress": on_progress} if on_progress else {}))
			if response.get("state") != "loaded":
				raise LLMProviderError(_("The model did not finish loading."))
			self._invalidate_caches()

	def ensure_running(self, record, *, on_progress=None, cancel_event=None) -> None:
		try:
			with cancellation_event_scope(cancel_event):
				self._ensure_running(record, on_progress=on_progress)
		except RequestCancelled as exc:
			if cancel_event is not None:
				raise DownloadCancelledError(_("Model loading cancelled.")) from exc
			raise

	def _ensure_running(self, record: LlamaModelRecord, *, on_progress=None) -> None:
		default_context = int(getattr(self._config, "num_ctx", 0) or 0)
		preset_path = self._catalog.write_preset(default_context=default_context)
		context = 0
		worker_client = self._worker_client or getattr(self._supervisor, "_get_worker_client", lambda: None)()
		if worker_client is not None:
			records = [
				{
					"model_id": item.model_id,
					"repo": item.repo,
					"file": item.file,
					"draft_repo": item.draft_repo,
					"draft_file": item.draft_file,
					"preset_options": dict(item.preset_options),
				}
				for item in self._catalog.export_records(default_context=default_context)
			]
			response = worker_client.send_command({
				"type": "llama_configure_preset",
				"command": "llama_configure_preset",
				"models": records,
				"default_model": record.model_id,
				"preset_path": str(preset_path),
				"executable": self._supervisor.executable,
			}, timeout=10.0)
			if response.get("type") == "error" or response.get("success") is False:
				raise LlamaServerError(response.get("error_message") or _("Could not configure the llama.cpp preset."))
		if self._supervisor.is_running and not self._supervisor.matches_startup_configuration(
			record.server_model, model_id=record.model_id, models_preset=preset_path, context=context):
			self._supervisor.stop()
		if not self._supervisor.is_running and not self._supervisor.is_adopted and self._supervisor.is_healthy():
			if not any(record.matches_server_id(str(item.get("id", "")))
					for item in self._supervisor.list_models(refresh=True)):
				raise LLMProviderError(_("A llama-server is already running with a different preset. Stop it before switching models."))
			self._supervisor.adopt(record.model_id)
			return
		if self._supervisor.is_running or self._supervisor.is_adopted:
			if self._supervisor.is_healthy():
				if any(record.matches_server_id(str(item.get("id", "")))
						for item in self._supervisor.list_models(refresh=True)):
					if not self._supervisor.is_running:
						self._supervisor.adopt(record.model_id)
					return
				raise LLMProviderError(_("llama-server does not expose preset {model_id}").format(model_id=record.model_id))
			self._supervisor.stop()
		self._supervisor.start(record.server_model, model_id=record.model_id,
			models_preset=preset_path, context=context, on_progress=on_progress)
		if not self._supervisor.wait_until_ready(on_progress=on_progress):
			raise LLMProviderError(_("llama-server did not become ready"))

	def _stop_owned_router(self) -> None:
		status = self._supervisor.status(refresh=True, strict=True)
		if status.is_running and not status.is_adopted:
			self._supervisor.stop(strict=True)

	def delete_model(self, model_id: str) -> None:
		record = self._catalog.find_exact(model_id)
		if record is None:
			raise LLMProviderError(_("This preset is not registered."))
		# The running router loaded the previous generated preset catalog. Stop
		# only our owned process before changing the catalog; adopted servers are
		# deliberately left untouched.
		self._stop_owned_router()
		active = self.active_model_id
		was_active = active == record.model_id or (active and record.matches_server_id(active))
		cleared = False
		if was_active:
			if self._clear_model_fn:
				cleared = bool(self._clear_model_fn(active, ""))
			else:
				if self._set_model_fn:
					self._set_model_fn("")
				if self._config is not None:
					object.__setattr__(self._config, "model_name", "")
				cleared = True
		try:
			self._catalog.remove(record.model_id)
		except Exception:
			if cleared and active:
				if self._set_model_fn:
					self._set_model_fn(active)
				if self._config is not None:
					object.__setattr__(self._config, "model_name", active)
			raise
		self._invalidate_caches()

	def close(self) -> None:
		return None

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
