# -*- coding: utf-8 -*-
"""Persistent llama.cpp model catalog and router preset generation."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
import re

from ..model_import import ModelSourceKind


@dataclass(frozen=True)
class LlamaModelRecord:
	model_id: str
	source: str
	kind: str
	revision: str = "main"
	artifact: str | None = None
	variant: str | None = None
	local_path: str | None = None

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
		return str(server_id or "").strip() in self.identities


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
		inputs = {str(value).lower() for value in architecture.get("input_modalities", [])}
		outputs = {str(value).lower() for value in architecture.get("output_modalities", [])}
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


def _record_source_lines(record: LlamaModelRecord) -> list[str]:
	if record.kind == ModelSourceKind.HUGGING_FACE.value:
		repository = record.source.strip()
		if record.variant:
			repository = f"{repository}:{record.variant}"
		return [f"hf-repo = {repository}"]
	path = str(Path(record.local_path or record.source).resolve())
	return [f"model = {path}"]


def build_models_preset(records: list[LlamaModelRecord]) -> str:
	"""Build a llama-server router preset without server-level settings."""
	lines = ["version = 1", ""]
	for record in records:
		model_id = record.model_id.strip()
		if not model_id or any(char in model_id for char in "[]\r\n"):
			continue
		lines.append(f"[{model_id}]")
		lines.extend(_record_source_lines(record))
		lines.append("")
	return "\n".join(lines)


_SECTION_RE = re.compile(r"^\[([^\]\r\n]+)\]\s*$")


def parse_models_preset(text: str) -> tuple[LlamaModelRecord, ...]:
	"""Read model identities from a llama-server preset without losing options."""
	sections: dict[str, dict[str, str]] = {}
	current: str | None = None
	for raw_line in text.splitlines():
		match = _SECTION_RE.match(raw_line.strip())
		if match:
			current = match.group(1).strip()
			sections.setdefault(current, {})
			continue
		if current is None or current == "*" or not raw_line.strip() or raw_line.lstrip().startswith("#"):
			continue
		if "=" in raw_line:
			key, value = raw_line.split("=", 1)
			sections[current][key.strip().lower()] = value.strip()
	records: list[LlamaModelRecord] = []
	for model_id, values in sections.items():
		hf_repo = values.get("hf-repo")
		model_path = values.get("model")
		if hf_repo:
			repository, _, variant = hf_repo.rpartition(":")
			if not repository:
				repository, variant = hf_repo, None
			records.append(LlamaModelRecord(model_id, repository, ModelSourceKind.HUGGING_FACE.value, variant=variant))
		elif model_path:
			records.append(LlamaModelRecord(model_id, model_path, ModelSourceKind.LOCAL_FILE.value, local_path=model_path))
	return tuple(records)


def merge_models_preset(text: str, records: list[LlamaModelRecord]) -> str:
	"""Reconcile model sources while preserving preset comments and options."""
	if not text.strip():
		return build_models_preset(records)
	lines = text.splitlines()
	sections: list[tuple[str, int, int]] = []
	for index, line in enumerate(lines):
		match = _SECTION_RE.match(line.strip())
		if match:
			if sections:
				sections[-1] = (sections[-1][0], sections[-1][1], index)
			sections.append((match.group(1).strip(), index, len(lines)))
	managed = {record.model_id: record for record in records}
	output = list(lines)
	for section, start, end in reversed(sections):
		record = managed.get(section)
		if record is None or section == "*":
			continue
		body = output[start + 1:end]
		body = [line for line in body if not re.match(r"^\s*(?:model|hf-repo)\s*=", line, re.I)]
		body = _record_source_lines(record) + body
		output[start + 1:end] = body
	existing = {section for section, _, _ in sections}
	for record in records:
		if record.model_id in existing:
			continue
		while output and not output[-1].strip():
			output.pop()
		output.extend(["", f"[{record.model_id}]", *_record_source_lines(record)])
	return "\n".join(output).rstrip() + "\n"


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
	"""Thread-safe JSON catalog with atomic persistence and preset export."""

	def __init__(self, directory: str | Path | None = None, preset_path: str | Path | None = None) -> None:
		self._directory = Path(directory) if directory else self._default_directory()
		self._manifest_path = self._directory / "models.json"
		self._preset_path = Path(preset_path) if preset_path else self._directory / "models.ini"
		self._lock = threading.RLock()

	@property
	def preset_path(self) -> Path:
		return self._preset_path

	def list_records(self) -> tuple[LlamaModelRecord, ...]:
		with self._lock:
			try:
				payload = json.loads(self._manifest_path.read_text(encoding="utf-8"))
			except (OSError, json.JSONDecodeError):
				payload = []
			records = tuple(
				LlamaModelRecord(**item)
				for item in payload
				if isinstance(item, dict) and item.get("model_id")
			)
			if self._preset_path.is_file():
				known = {record.model_id for record in records}
				records += tuple(record for record in parse_models_preset(self._preset_path.read_text(encoding="utf-8")) if record.model_id not in known)
			return records

	def upsert(self, record: LlamaModelRecord) -> None:
		with self._lock:
			records = [item for item in self.list_records() if item.model_id != record.model_id]
			records.append(record)
			self._write_records(records)

	def remove(self, model_id: str) -> None:
		with self._lock:
			self._write_records([item for item in self.list_records() if item.model_id != model_id])
			if self._preset_path.is_file():
				content = self._preset_path.read_text(encoding="utf-8")
				self._preset_path.write_text(remove_model_from_preset(content, model_id), encoding="utf-8", newline="\n")

	def find(self, model_id: str) -> LlamaModelRecord | None:
		requested = str(model_id or "").strip()
		for item in self.list_records():
			if item.matches_server_id(requested):
				return item
		return None

	def write_preset(self) -> Path:
		with self._lock:
			self._preset_path.parent.mkdir(parents=True, exist_ok=True)
			try:
				content = self._preset_path.read_text(encoding="utf-8")
			except OSError:
				content = ""
			content = merge_models_preset(content, list(self.list_records()))
			fd, temporary_name = tempfile.mkstemp(prefix="models-", suffix=".ini", dir=self._preset_path.parent)
			try:
				with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
					handle.write(content)
				Path(temporary_name).replace(self._preset_path)
			except Exception:
				try:
					Path(temporary_name).unlink(missing_ok=True)
				except OSError:
					pass
				raise
			return self._preset_path

	def _write_records(self, records: list[LlamaModelRecord]) -> None:
		self._directory.mkdir(parents=True, exist_ok=True)
		fd, temporary_name = tempfile.mkstemp(prefix="models-", suffix=".json", dir=self._directory)
		try:
			with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
				json.dump([asdict(item) for item in records], handle, indent=2)
				handle.write("\n")
			Path(temporary_name).replace(self._manifest_path)
		except Exception:
			try:
				Path(temporary_name).unlink(missing_ok=True)
			except OSError:
				pass
			raise

	@staticmethod
	def _default_directory() -> Path:
		base = Path(os.getenv("APPDATA") or (Path.home() / "AppData" / "Roaming"))
		return base / "nvda" / "AIAssistant" / "models" / "llama-cpp"
