# -*- coding: utf-8 -*-
"""Persistent HF-only llama.cpp presets and derived router preset."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ...core.llama_preset import LlamaPresetCodec, build_models_preset as _build_preset, validate_preset_model
from ...core.translation import _


@dataclass(frozen=True)
class LlamaModelRecord:
	model_id: str
	repo: str
	file: str | None = None
	draft_repo: str | None = None
	draft_file: str | None = None
	preset_options: dict[str, str] = field(default_factory=dict)
	display_name: str = ""
	spec_type_auto: bool = False

	@property
	def server_model(self) -> str:
		return f"hf://{self.repo}"

	@property
	def context_window(self) -> int | None:
		try:
			value = int(self.preset_options.get("ctx-size", 0) or 0)
		except (TypeError, ValueError):
			return None
		return value or None

	@property
	def capabilities(self) -> tuple[str, ...]:
		caps = {"chat", "completion", "streaming", "text_input", "text_output"}
		if self.preset_options.get("reasoning") in {"on", "auto"} or self.preset_options.get("reasoning-format") not in {None, "none"}:
			caps.add("thinking")
		return tuple(sorted(caps))

	@property
	def identities(self) -> frozenset[str]:
		values = {self.model_id, self.repo, f"hf://{self.repo}", self.server_model.removeprefix("hf://")}
		if self.file:
			values.update({self.file, f"{self.repo}#file={self.file}", f"hf://{self.repo}#file={self.file}"})
		return frozenset(value for value in values if value)

	def matches_server_id(self, server_id: str) -> bool:
		value = str(server_id or "").strip()
		return bool(value) and value.lower() in {identity.lower() for identity in self.identities}


def llama_model_capabilities(item: dict[str, object]) -> tuple[str, ...]:
	caps = {"chat", "completion", "streaming", "text_input", "text_output"}
	status = item.get("status")
	if isinstance(status, dict):
		args = status.get("args")
		if isinstance(args, list):
			normalized = [str(value).strip().lower() for value in args]
			for index, value in enumerate(normalized[:-1]):
				if value == "--reasoning" and normalized[index + 1] not in {"off", "false", "none"}:
					caps.add("thinking")
					break
				if value == "--reasoning-format" and normalized[index + 1] not in {"none", "off"}:
					caps.add("thinking")
					break
	architecture = item.get("architecture")
	if isinstance(architecture, dict):
		def modalities(key):
			values = architecture.get(key)
			return {str(value).lower() for value in values} if isinstance(values, list) else set()
		if "image" in modalities("input_modalities"):
			caps.add("image_input")
		if "audio" in modalities("input_modalities"):
			caps.add("audio_input")
		if "image" in modalities("output_modalities"):
			caps.add("image_output")
	return tuple(sorted(caps))


def llama_model_context_window(item: dict[str, object]) -> int | None:
	meta = item.get("meta")
	if not isinstance(meta, dict):
		return None
	try:
		value = int(meta.get("n_ctx_train", 0) or 0)
	except (TypeError, ValueError):
		return None
	return value or None


def build_models_preset(records: list[LlamaModelRecord]) -> str:
	return _build_preset(records)


class LlamaModelCatalog:
	"""Authoritative HF presets with an atomic derived preset file."""
	_locks: dict[str, threading.RLock] = {}
	_locks_guard = threading.Lock()

	def __init__(self, directory: str | Path | None = None) -> None:
		self._directory = (Path(directory) if directory else self._default_directory()).resolve()
		self._manifest_path = self._directory / "models.json"
		self._preset_path = self._directory / "runtime-models.ini"
		self._codec = LlamaPresetCodec()
		with self._locks_guard:
			self._lock = self._locks.setdefault(str(self._manifest_path), threading.RLock())

	@property
	def lock(self):
		return self._lock

	@property
	def preset_path(self) -> Path:
		return self._preset_path

	def _read_manifest(self) -> list[LlamaModelRecord]:
		try:
			payload = json.loads(self._manifest_path.read_text(encoding="utf-8"))
		except FileNotFoundError:
			return []
		except (OSError, json.JSONDecodeError) as exc:
			raise ValueError(_("Unable to read the llama.cpp preset catalog: {error}").format(error=exc)) from exc
		# No migration: only the current schema is read.
		if not isinstance(payload, dict) or payload.get("version") != 2 or not isinstance(payload.get("models"), list):
			return []
		fields = set(LlamaModelRecord.__dataclass_fields__)
		records = []
		for item in payload["models"]:
			if not isinstance(item, dict):
				continue
			values = {key: value for key, value in item.items() if key in fields}
			if not isinstance(values.get("repo"), str) or not values["repo"]:
				continue
			values["preset_options"] = dict(values.get("preset_options") or {})
			values["spec_type_auto"] = bool(values.get("spec_type_auto", False))
			try:
				records.append(LlamaModelRecord(**values))
			except (TypeError, ValueError):
				continue
		return records

	def list_records(self) -> tuple[LlamaModelRecord, ...]:
		with self._lock:
			return tuple(sorted(self._read_manifest(), key=lambda record: record.model_id))

	def update_options(self, model_id: str, options: dict[str, str]) -> None:
		with self._lock:
			record = self.find_exact(model_id)
			if record is None:
				raise ValueError(_("This preset is not registered."))
			fields = validate_preset_model(record.model_id, record.repo, record.file,
				record.draft_repo, record.draft_file, options)
			updated = LlamaModelRecord(display_name=record.display_name,
				spec_type_auto=record.spec_type_auto, **fields)
			self._commit([updated if item.model_id == model_id else item for item in self.list_records()])

	def upsert(self, record: LlamaModelRecord) -> None:
		with self._lock:
			fields = validate_preset_model(record.model_id, record.repo, record.file,
				record.draft_repo, record.draft_file, record.preset_options)
			validated = LlamaModelRecord(display_name=record.display_name,
				spec_type_auto=record.spec_type_auto, **fields)
			records = [item for item in self.list_records() if item.model_id != validated.model_id]
			records.append(validated)
			self._commit(records)

	def remove(self, model_id: str) -> bool:
		with self._lock:
			records = self.list_records()
			if not any(record.model_id == model_id for record in records):
				return False
			self._commit([record for record in records if record.model_id != model_id])
			return True

	def find_exact(self, model_id: str) -> LlamaModelRecord | None:
		return next((record for record in self.list_records() if record.model_id == model_id), None)

	def find(self, model_id: str) -> LlamaModelRecord | None:
		requested = str(model_id or "").strip()
		if not requested:
			return None
		exact = self.find_exact(requested)
		if exact is not None:
			return exact
		for record in self.list_records():
			if record.matches_server_id(requested):
				return record
		return None

	def export_records(self, *, default_context: int = 0) -> tuple[LlamaModelRecord, ...]:
		return tuple(
			LlamaModelRecord(**{**asdict(record), "preset_options": {**record.preset_options, "ctx-size": str(default_context)}})
			if default_context > 0 and record.context_window is None and "ctx-size" not in record.preset_options else record
			for record in self.list_records()
		)

	def write_preset(self, *, default_context: int = 0) -> Path:
		with self._lock:
			content = self._codec.encode(list(self.export_records(default_context=default_context)))
			self._atomic_write(self._preset_path, content.encode("utf-8"))
			return self._preset_path

	def _commit(self, records) -> None:
		content = self._codec.encode(list(records))
		before = self._manifest_path.read_bytes() if self._manifest_path.exists() else None
		self._write_records(records)
		try:
			self._atomic_write(self._preset_path, content.encode("utf-8"))
		except Exception:
			if before is None:
				self._manifest_path.unlink(missing_ok=True)
			else:
				self._atomic_write(self._manifest_path, before)
			raise

	def _write_records(self, records) -> None:
		payload = {
			"version": 2,
			"models": [asdict(record) for record in sorted(records, key=lambda record: record.model_id)],
		}
		self._atomic_write(self._manifest_path, (json.dumps(payload, indent=2) + "\n").encode("utf-8"))

	@staticmethod
	def _atomic_write(path: Path, content: bytes) -> None:
		path.parent.mkdir(parents=True, exist_ok=True)
		fd, temporary = tempfile.mkstemp(prefix="models-", suffix=path.suffix, dir=path.parent)
		try:
			with os.fdopen(fd, "wb") as handle:
				handle.write(content)
			Path(temporary).replace(path)
		finally:
			Path(temporary).unlink(missing_ok=True)

	@staticmethod
	def _default_directory() -> Path:
		base = Path(os.getenv("APPDATA") or (Path.home() / "AppData" / "Roaming"))
		return base / "nvda" / "AIAssistant" / "models" / "llama-cpp"
