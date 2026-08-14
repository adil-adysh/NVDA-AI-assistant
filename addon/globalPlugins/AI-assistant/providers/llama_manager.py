# -*- coding: utf-8 -*-
"""Model management for the llama.cpp server provider."""

from __future__ import annotations

import threading
import urllib.parse
from pathlib import Path

from logHandler import log

from .interfaces import LLMProviderError
from .model_import import (
	ModelImportRequest,
	ModelSourceKind,
	parse_model_import_source,
)
from .model_manager import (
	DownloadProgressCallback,
	ManagedModel,
	ModelManagerProvider,
	ModelState,
	ProviderFeatures,
)
from .runtime.llama_server import (
	LlamaServerSupervisor,
	default_llama_server_executable,
	get_llama_supervisor,
)
from .runtime.llama_models import LlamaModelCatalog, LlamaModelRecord, llama_model_capabilities


class LlamaCppModelManager(ModelManagerProvider):
	"""Owns imported GGUF references and the llama-server process."""

	provider_id = "llama-cpp-server"

	def __init__(
		self,
		config: object | None = None,
		*,
		supervisor: LlamaServerSupervisor | None = None,
		cache_dir: str | Path | None = None,
	) -> None:
		self._config = config
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
			)
		self._lock = threading.RLock()

	@property
	def features(self) -> ProviderFeatures:
		return ProviderFeatures(download=True, delete=True, import_model=True)

	@property
	def active_model_id(self) -> str | None:
		value = getattr(self._config, "model_name", "") if self._config else ""
		return str(value or "").strip() or None

	def list_managed_models(self) -> list[ManagedModel]:
		models: dict[str, ManagedModel] = {}
		server_items = self._supervisor.list_models()
		for record in self._catalog.list_records():
			ready = record.kind == ModelSourceKind.HUGGING_FACE.value or (
				record.local_path is not None and Path(record.local_path).is_file()
			)
			server_item = next(
				(item for item in server_items if record.matches_server_id(str(item.get("id", "")))),
				None,
			)
			models[record.model_id] = ManagedModel(
				id=record.model_id,
				display_name=record.model_id,
				state=ModelState.DOWNLOADED if ready else ModelState.NOT_DOWNLOADED,
				capabilities=llama_model_capabilities(server_item) if server_item else (
					"chat", "completion", "streaming", "text_input", "text_output"
				),
			)
		for item in server_items:
			model_id = str(item.get("id", "")).strip()
			if model_id and model_id not in models:
				models[model_id] = ManagedModel(
					id=model_id,
					display_name=model_id,
					state=ModelState.DOWNLOADED,
					capabilities=llama_model_capabilities(item),
				)
		return sorted(models.values(), key=lambda model: model.display_name.lower())

	def list_server_models(self, *, refresh: bool = False) -> tuple[dict[str, object], ...]:
		"""Return the cached authoritative llama-server model catalog."""
		return self._supervisor.list_models(refresh=refresh)

	def import_model(
		self,
		request: ModelImportRequest,
		on_progress: DownloadProgressCallback,
		cancel_event: threading.Event | None = None,
	) -> None:
		if cancel_event is not None and cancel_event.is_set():
			return
		try:
			parsed = parse_model_import_source(
				request.source,
				request.model_id,
				self.provider_id,
			)
		except ValueError as exc:
			raise LLMProviderError(str(exc)) from exc
		if parsed.file_suffix and parsed.file_suffix != ".gguf":
			raise LLMProviderError("llama-server imports require a .gguf file or Hugging Face GGUF repository")
		local_path: str | None = None
		if parsed.kind is ModelSourceKind.LOCAL_FILE:
			local_path = str(Path(parsed.source).resolve())
			on_progress("Registering local GGUF model", None, None)
		else:
			on_progress("Registering Hugging Face GGUF variant", None, None)
		record = LlamaModelRecord(
			model_id=parsed.model_id,
			source=parsed.source,
			kind=parsed.kind.value,
			revision=parsed.revision,
			artifact=parsed.artifact,
			variant=parsed.variant,
			local_path=local_path,
		)
		self._catalog.upsert(record)
		on_progress(f"Model {record.model_id} is ready to start", None, None)

	def download_model(
		self,
		model_id: str,
		on_progress: DownloadProgressCallback,
		cancel_event: threading.Event | None = None,
	) -> None:
		record = self._find_record(model_id)
		if record is None:
			raise LLMProviderError(f"Unknown llama.cpp model: {model_id}")
		self.ensure_running(record, on_progress=lambda message: on_progress(message, None, None), cancel_event=cancel_event)

	def ensure_running(
		self,
		record: LlamaModelRecord,
		*,
		on_progress=None,
		cancel_event: threading.Event | None = None,
	) -> None:
		if cancel_event is not None and cancel_event.is_set():
			return
		requested_model = record.model_id
		preset_path = self._catalog.write_preset()
		# Recover a server left behind by a previous NVDA process.  Only adopt
		# it when the requested model is already exposed by that server; a
		# handleless process cannot be safely terminated or reconfigured here.
		if not self._supervisor.is_running and not self._supervisor.is_adopted and self._supervisor.is_healthy():
			if not any(
				record.matches_server_id(str(item.get("id", "")))
				for item in self._supervisor.list_models()
			):
				raise LLMProviderError(
					"A llama-server is already running with a different model preset. "
					"Stop it before switching models."
				)
			self._supervisor.adopt(requested_model)
			return
		if self._supervisor.is_running or self._supervisor.is_adopted:
			if self._supervisor.is_healthy():
				if any(
					record.matches_server_id(str(item.get("id", "")))
					for item in self._supervisor.list_models()
				):
					# llama-server is a router: model selection is carried by the
					# OpenAI-compatible request, so switching does not restart it.
					if not self._supervisor.is_running:
						self._supervisor.adopt(requested_model)
					return
				raise LLMProviderError(
					f"llama-server does not expose model {requested_model!r} in its API"
				)
			else:
				self._supervisor.stop()
		self._supervisor.start(
			record.server_model,
			model_id=record.model_id,
			models_preset=preset_path,
			context=int(getattr(self._config, "num_ctx", 0) or 0),
			on_progress=on_progress,
		)
		if not self._supervisor.wait_until_ready(on_progress=on_progress):
			raise LLMProviderError("llama-server did not become ready")

	def delete_model(self, model_id: str) -> None:
		record = self._find_record(model_id)
		if record is None:
			raise LLMProviderError(f"Unknown llama.cpp model: {model_id}")
		if record.local_path and Path(record.local_path).is_file():
			# Imported local files remain user-owned.  Removing a model only removes
			# our manifest entry, never the user's source file.
			log.info("Keeping user-owned GGUF source %s", record.local_path)
		self._remove_record(record.model_id)

	def set_active_model(self, model_id: str) -> None:
		if self._find_record(model_id) is None and model_id not in {
			str(item.get("id", "")) for item in self._supervisor.list_models()
		}:
			raise LLMProviderError(f"Unknown llama.cpp model: {model_id}")
		if self._config is not None:
			# Registry supplies the durable setter; this assignment is only for
			# callers that construct the manager directly in tests.
			try:
				object.__setattr__(self._config, "model_name", model_id)
			except Exception:
				pass

	def get_available_model_ids(self) -> list[str]:
		return [model.id for model in self.list_managed_models() if model.state.is_ready()]

	def resolve_model_identity(self, model_id: str) -> str:
		return str(model_id).strip()

	def close(self) -> None:
		# Provider instances are short-lived; application shutdown owns the
		# shared server process.
		return None

	def find_record(self, model_id: str) -> LlamaModelRecord | None:
		"""Return the persisted source identity for an imported model."""
		return self._find_record(model_id)

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
