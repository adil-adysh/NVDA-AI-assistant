# -*- coding: utf-8 -*-
"""Persistent llama.cpp model catalog and router preset generation."""

from __future__ import annotations
from ...core.llama_model_source import validate_standalone_gguf
from ...core.llama_companions import validate_companions

import hashlib
import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
import re

from ..model_import import ModelSourceKind
from ...core.llama_preset import LlamaPresetCodec, build_models_preset as _build_preset, merge_models_preset as _merge_preset
from ...core.translation import _
from ...core.llama_options import canonical_key, SOURCE_KEYS, OPTION_BY_KEY, validate_options


@dataclass(frozen=True)
class LlamaModelRecord:
	model_id: str
	source: str
	kind: str
	revision: str = "main"
	artifact: str | None = None
	variant: str | None = None
	local_path: str | None = None
	context_window: int | None = None
	capabilities: tuple[str, ...] = ("chat", "completion", "streaming", "text_input", "text_output")
	ownership: str = "user"
	cached_path: str | None = None
	from_preset: bool = False
	preset_options: dict[str, str] = field(default_factory=dict)
	display_name: str = ""
	asset_id: str | None = None
	asset_source: str = ""
	asset_repository: str | None = None
	asset_revision: str | None = None
	asset_artifact: str | None = None
	companions: tuple[dict, ...] = ()

	def __post_init__(self):
		object.__setattr__(self, "companions", validate_companions(self.companions))


	@property
	def server_model(self) -> str:
		if self.kind == ModelSourceKind.HUGGING_FACE.value:
			value = self.source
			if self.variant:
				value = f"{value}:{self.variant}"
			return f"hf://{value}"
		return self.local_path or self.source

	@property
	def identities(self) -> frozenset[str]:
		values = {
			self.model_id,
			self.source,
			self.server_model,
			self.server_model.removeprefix("hf://"),
		}
		if self.variant:
			values.add(f"{self.source}:{self.variant}")
		return frozenset(value for value in values if value)

	def matches_server_id(self, server_id: str) -> bool:
		server_id_str = str(server_id or "").strip()
		if not server_id_str:
			return False
		server_id_lower = server_id_str.lower()
		for identity in self.identities:
			identity_clean = identity.strip()
			if identity_clean == server_id_str or identity_clean.lower() == server_id_lower:
				return True
		return False


@dataclass(frozen=True)
class PresetImportSummary:
	model_ids: tuple[str, ...]
	option_count: int
	source: str


@dataclass(frozen=True)
class PresetImportPreview:
	source: str
	digest: str
	records: tuple[LlamaModelRecord, ...]
	replace_ids: tuple[str, ...]
	unsupported: tuple[str, ...]
	catalog_digest: str


def llama_model_capabilities(item: dict[str, object]) -> tuple[str, ...]:
	"""Normalize llama-server architecture metadata to provider capabilities."""
	caps = {"chat", "completion", "streaming", "text_input", "text_output"}
	status = item.get("status")
	if isinstance(status, dict):
		args = status.get("args")
		if isinstance(args, list):
			normalized_args = [str(value).strip().lower() for value in args]
			for index, value in enumerate(normalized_args[:-1]):
				if value != "--reasoning":
					continue
				reasoning_value = normalized_args[index + 1]
				if reasoning_value not in {"off", "false", "none"}:
					caps.add("thinking")
					break
			for index, value in enumerate(normalized_args[:-1]):
				if value == "--reasoning-format" and normalized_args[index + 1] not in {"none", "off"}:
					caps.add("thinking")
					break
	architecture = item.get("architecture")
	if isinstance(architecture, dict):
		def modalities(key):
			values = architecture.get(key)
			return {str(value).lower() for value in values} if isinstance(values, list) else set()
		inputs = modalities("input_modalities")
		outputs = modalities("output_modalities")
		if "image" in inputs:
			caps.add("image_input")
		if "audio" in inputs:
			caps.add("audio_input")
		if "image" in outputs:
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


_SECTION_RE = re.compile(r"^\[([^\]\r\n]+)\]\s*$")


def parse_models_preset(text: str, *, base_directory: Path | None = None, strict: bool = False) -> tuple[LlamaModelRecord, ...]:
	"""Read model identities from a llama-server preset without losing options."""
	sections: dict[str, dict[str, str]] = {}
	current: str | None = None
	for raw_line in text.splitlines():
		match = _SECTION_RE.match(raw_line.strip())
		if match:
			current = match.group(1).strip()
			sections.setdefault(current, {})
			continue
		if not raw_line.strip() or raw_line.lstrip().startswith(("#", ";")):
			continue
		if current is None:
			if strict and raw_line.split("=", 1)[0].strip() != "version":
				raise ValueError(_("Only the version option is supported outside preset sections."))
			continue
		if "=" in raw_line:
			key, value = raw_line.split("=", 1)
			key = canonical_key(key.strip())
			if strict and key in sections[current]:
				raise ValueError(_("Duplicate llama.cpp preset option: {option}.").format(option=key))
			sections[current][key] = value.strip()
	if strict:
		unsupported = sorted({f"[{section}] {key}" for section, values in sections.items()
			for key in values if key not in SOURCE_KEYS and key not in OPTION_BY_KEY})
		if unsupported:
			raise ValueError(_("Preset import was not completed. Unsupported options: {options}. Remove or replace these options in a copy of the file and import again.").format(options=", ".join(unsupported)))
	records: list[LlamaModelRecord] = []
	for model_id, values in sections.items():
		if model_id == "*":
			continue
		values = {**sections.get("*", {}), **values}
		options = validate_options({key: value for key, value in values.items() if key in OPTION_BY_KEY}) if strict else {}
		for path_option in ("mmproj", "spec-draft-model"):
			if path_option in options and base_directory is not None and not Path(options[path_option]).is_absolute():
				options[path_option] = str((base_directory / options[path_option]).resolve())
		hf_repo = values.get("hf-repo")
		model_path = values.get("model")
		if strict:
			if model_path and hf_repo or values.get("hf-file") and not hf_repo:
				raise ValueError(_("Preset models must use either a local model path or a Hugging Face repository; hf-file requires hf-repo."))
			if hf_repo:
				from ..model_import import parse_model_import_source
				parsed_source = parse_model_import_source(hf_repo, model_id, "llama-cpp-server")
				if parsed_source.is_local_file or parsed_source.revision != "main":
					raise ValueError(_("llama.cpp presets support Hugging Face repositories on the main revision only."))
			if model_path:
				validate_standalone_gguf(model_path)
			if values.get("hf-file"):
				validate_standalone_gguf(values["hf-file"])
		if model_path and base_directory is not None and not Path(model_path).is_absolute():
			model_path = str((base_directory / model_path).resolve())
		ctx_size: int | None = None
		try:
			raw_ctx = values.get("ctx-size")
			if raw_ctx:
				ctx_size = int(raw_ctx)
		except (ValueError, TypeError):
			pass
		caps = {"chat", "completion", "streaming", "text_input", "text_output"}
		reasoning = values.get("reasoning", "").lower()
		reasoning_format = values.get("reasoning-format", "").lower()
		if reasoning in {"on", "true", "yes", "auto"} or (reasoning_format and reasoning_format not in {"none", "off"}):
			caps.add("thinking")
		caps_tuple = tuple(sorted(caps))
		if options.get("mmproj"):
			caps_tuple = tuple(sorted({*caps_tuple, "image_input"}))
		if hf_repo:
			artifact = values.get("hf-file")
			if strict:
				repository, variant = parsed_source.source, parsed_source.variant
				if artifact and parsed_source.artifact and artifact != parsed_source.artifact:
					raise ValueError(_("Conflicting Hugging Face artifact selectors. Use one hf-file value."))
				artifact = artifact or parsed_source.artifact
			else:
				repository, separator, variant = hf_repo.rpartition(":")
				if not repository:
					repository, variant = hf_repo, None
			records.append(LlamaModelRecord(
				model_id,
				repository,
				ModelSourceKind.HUGGING_FACE.value,
				variant=variant,
				artifact=artifact,
				context_window=ctx_size,
				capabilities=caps_tuple,
				preset_options=options,
			))
		elif model_path:
			records.append(LlamaModelRecord(
				model_id,
				model_path,
				ModelSourceKind.LOCAL_FILE.value,
				local_path=model_path,
				context_window=ctx_size,
				capabilities=caps_tuple,
				preset_options=options,
			))
		elif strict:
			raise ValueError(_("Preset model {model} has no model path or Hugging Face repository. Import its source explicitly first.").format(model=model_id))
	return tuple(records)


def merge_models_preset(text: str, records: list[LlamaModelRecord]) -> str:
	return _merge_preset(text, records)


def remove_model_from_preset(text: str, model_id: str) -> str:
	"""Remove one model section while retaining the global preset settings."""
	lines = text.splitlines()
	sections: list[tuple[str, int, int]] = []
	for index, line in enumerate(lines):
		match = _SECTION_RE.match(line.strip())
		if match:
			if sections:
				sections[-1] = (sections[-1][0], sections[-1][1], index)
			sections.append((match.group(1).strip(), index, len(lines)))
	for section, start, end in reversed(sections):
		if section == model_id:
			del lines[start:end]
	return "\n".join(lines).rstrip() + "\n"


class LlamaModelCatalog:
	"""Authoritative registrations with an atomic, derived runtime preset."""
	_locks: dict[str, threading.RLock] = {}
	_locks_guard = threading.Lock()

	def __init__(self, directory: str | Path | None = None, preset_path: str | Path | None = None) -> None:
		self._directory = (Path(directory) if directory else self._default_directory()).resolve()
		self._user_preset = Path(preset_path).resolve() if preset_path else None
		self._source_preset = self._user_preset or self._directory / "models.ini"
		self._manifest_path = self._directory / "models.json"
		self._preset_path = self._directory / "runtime-models.ini"
		self._codec = LlamaPresetCodec()
		self._migration_complete = False
		with self._locks_guard:
			self._lock = self._locks.setdefault(str(self._manifest_path), threading.RLock())

	@property
	def lock(self):
		return self._lock

	@property
	def cache_directory(self) -> Path:
		return self._directory / "cache"

	@property
	def preset_path(self) -> Path:
		return self._preset_path

	def _read_manifest(self):
		path = self._manifest_path

		try:
			payload = json.loads(path.read_text(encoding="utf-8"))
		except FileNotFoundError:
			return [], set(), set()
		except (OSError, json.JSONDecodeError) as exc:
			raise ValueError(_("Unable to read the llama.cpp model catalog: {error}").format(error=exc)) from exc
		removed = set()
		removed_models = set()
		if isinstance(payload, dict):
			if payload.get("version") != 1:
				raise ValueError(_("Unsupported llama.cpp model catalog version."))
			removed = {value for value in payload.get("removed_ids", []) if isinstance(value, str)}
			removed_models = {value for value in payload.get("removed_models", []) if isinstance(value, str)}
			payload = payload.get("models", [])
		if not isinstance(payload, list):
			raise ValueError(_("Invalid llama.cpp model catalog."))
		keys = set(LlamaModelRecord.__dataclass_fields__)
		records = []
		for item in payload:
			if not isinstance(item, dict) or not all(isinstance(item.get(key), str) and item[key] for key in ("model_id", "source", "kind")):
				continue
			values = {key: value for key, value in item.items() if key in keys}
			if self._user_preset and "from_preset" not in item:
				values["from_preset"] = True
			values["capabilities"] = tuple(values.get("capabilities") or ("chat", "completion", "streaming", "text_input", "text_output"))
			records.append(LlamaModelRecord(**values))
		return records, removed, removed_models

	def _source_text(self) -> str:
		try:
			text = self._source_preset.read_text(encoding="utf-8-sig")
		except FileNotFoundError:
			if self._user_preset is not None:
				raise ValueError(_("The configured llama.cpp preset no longer exists."))
			return ""
		self._codec.validate(text)
		return text

	def _ensure_migrated(self) -> None:
		if self._migration_complete:
			return
		payload = {}
		if self._manifest_path.exists():
			payload = json.loads(self._manifest_path.read_text(encoding="utf-8"))
		if isinstance(payload, dict) and payload.get("authoritative") is True:
			self._migration_complete = True
			return
		records, removed, removed_models = self._read_manifest()
		if self._user_preset:
			suffix = hashlib.sha256(str(self._user_preset).encode()).hexdigest()[:16]
			legacy_path = self._directory / f"models-{suffix}.json"
			if legacy_path.exists():
				current_path = self._manifest_path
				try:
					self._manifest_path = legacy_path
					legacy, retired, retired_models = self._read_manifest()
				finally:
					self._manifest_path = current_path
				records = list({record.model_id: record for record in [*records, *legacy]}.values())
				removed |= retired
				removed_models |= retired_models
		if self._source_preset.exists():
			imported = parse_models_preset(self._source_text(), base_directory=self._source_preset.parent, strict=True)
			by_id = {record.model_id: record for record in imported if record.model_id not in removed_models}
			for record in records:
				if record.model_id not in removed_models:
					base = by_id.get(record.model_id)
					by_id[record.model_id] = replace(base if base and record.from_preset else record, preset_options=base.preset_options if base else record.preset_options, from_preset=False)
			records = list(by_id.values())
		elif self._user_preset and not records:
			raise ValueError(_("The configured llama.cpp preset no longer exists."))
		if records or self._manifest_path.exists() or self._source_preset.exists():
			self._persist(records, removed, removed_models)
		self._migration_complete = True

	def list_records(self) -> tuple[LlamaModelRecord, ...]:
		with self._lock:
			self._ensure_migrated()
			return tuple(sorted(self._read_manifest()[0], key=lambda record: record.model_id))

	def import_preset(self, path: str | Path) -> PresetImportSummary:
		"""Import a validated snapshot; never retain a live file dependency."""
		source = Path(path).resolve()
		text = source.read_text(encoding="utf-8-sig")
		self._codec.validate(text)
		records = parse_models_preset(text, base_directory=source.parent, strict=True)
		if not records:
			raise ValueError(_("The preset contains no importable models."))
		self._codec.encode(list(records))
		return self.import_records(records, source=str(source))

	def import_records(self, records, *, source: str) -> PresetImportSummary:
		self._codec.encode(list(records))
		with self._lock:
			# Explicit import can repair an unsupported legacy preset. Validation
			# above completes before we change the catalog's migration state.
			previous_migration = self._migration_complete
			self._migration_complete = True
			by_id = {record.model_id: record for record in self._read_manifest()[0]}
			removed = set(self.removed_identities())
			for record in records:
				by_id[record.model_id] = record
				removed -= record.identities
			try:
				self._commit(list(by_id.values()), removed)
			except Exception:
				self._migration_complete = previous_migration
				raise
		return PresetImportSummary(tuple(record.model_id for record in records), sum(len(record.preset_options) for record in records), source)

	def update_options(self, model_id: str, options: dict[str, str]) -> None:
		validated = validate_options(options)
		with self._lock:
			record = self.find_exact(model_id)
			if record is None:
				raise ValueError(_("This model is not registered in the add-on."))
			caps = set(record.capabilities) - {"thinking", "image_input"}
			if validated.get("reasoning") in {"on", "auto"} or validated.get("reasoning-format") not in {None, "none"}:
				caps.add("thinking")
			if validated.get("mmproj"):
				caps.add("image_input")
			self.upsert(replace(record, preset_options=validated, context_window=None, capabilities=tuple(sorted(caps)),
				companions=tuple({**value, "compatibility": "unverified"} for value in record.companions)))

	def removed_identities(self) -> frozenset[str]:
		with self._lock:
			return frozenset(self._read_manifest()[1])

	def _commit(self, records, removed) -> None:
		old_models = self._read_manifest()[2]
		current_ids = {record.model_id for record in records}
		removed_models = (old_models | ({record.model_id for record in self.list_records()} - current_ids)) - current_ids
		self._persist(records, removed, removed_models)

	def _persist(self, records, removed, removed_models) -> None:
		content = self._codec.encode(records)
		before = self._manifest_path.read_bytes() if self._manifest_path.exists() else None
		self._write_records(records, removed, removed_models)
		try:
			self._atomic_preset(content)
		except Exception:
			if before is None:
				self._manifest_path.unlink(missing_ok=True)
			else:
				self._atomic_write(self._manifest_path, before)
			raise

	def upsert(self, record: LlamaModelRecord) -> None:
		if not record.model_id.strip() or any(char in record.model_id for char in "[]*") or any(ord(char) < 32 for char in record.model_id):
			raise ValueError(_("Invalid llama.cpp preset model ID."))
		with self._lock:
			self._codec.encode([record])  # Validate before persisting anything.
			records = [item for item in self.list_records() if item.model_id != record.model_id]
			records.append(record)
			removed = set(self.removed_identities()) - set(record.identities)
			self._commit(records, removed)

	def remove(self, model_id: str) -> bool:
		with self._lock:
			records = self.list_records()
			record = next((item for item in records if item.model_id == model_id), None)
			if record is None:
				return False
			removed = set(self.removed_identities()) | set(record.identities)
			self._commit([item for item in records if item.model_id != model_id], removed)
			return True

	def find_exact(self, model_id: str) -> LlamaModelRecord | None:
		return next((record for record in self.list_records() if record.model_id == model_id), None)

	def find(self, model_id: str, *, register_missing: bool = True) -> LlamaModelRecord | None:
		requested = str(model_id or "").strip()
		if not requested:
			return None
		exact = self.find_exact(requested)
		if exact is not None:
			return exact
		if requested in self.removed_identities():
			return None
		for item in self.list_records():
			if item.matches_server_id(requested):
				return item
		if not register_missing:
			return None
		if requested.startswith("hf://") or "/" in requested or Path(requested).suffix.lower() == ".gguf":
			try:
				from ..model_import import parse_model_import_source
				parsed = parse_model_import_source(requested, None, "llama-cpp-server")
				if parsed.revision != "main":
					return None
				record = LlamaModelRecord(parsed.model_id, parsed.source, parsed.kind.value,
					revision=parsed.revision, artifact=parsed.artifact, variant=parsed.variant,
					local_path=str(Path(parsed.source).resolve()) if parsed.is_local_file else None)
				self.upsert(record)
				return record
			except (ValueError, OSError):
				pass
		return None

	def export_records(self, *, default_context: int = 0) -> tuple[LlamaModelRecord, ...]:
		"""Apply provider defaults only to unpinned records in the derived export."""
		return tuple(replace(record, preset_options={**record.preset_options, "ctx-size": str(default_context)})
			if default_context > 0 and record.context_window is None and "ctx-size" not in record.preset_options else record
			for record in self.list_records())

	def write_preset(self, *, default_context: int = 0) -> Path:
		with self._lock:
			content = self._codec.encode(list(self.export_records(default_context=default_context)))
			self._atomic_preset(content)
			return self._preset_path

	def _atomic_preset(self, content: str) -> None:
		self._atomic_write(self._preset_path, content.encode("utf-8"))

	def _write_records(self, records, removed=(), removed_models=()) -> None:
		payload = {"version": 1, "authoritative": True, "models": [asdict(record) for record in sorted(records, key=lambda record: record.model_id)], "removed_ids": sorted(removed), "removed_models": sorted(removed_models)}
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
