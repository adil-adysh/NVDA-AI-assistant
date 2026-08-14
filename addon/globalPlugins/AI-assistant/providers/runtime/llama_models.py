# -*- coding: utf-8 -*-
"""Persistent llama.cpp model catalog and router preset generation."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

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


def build_models_preset(records: list[LlamaModelRecord]) -> str:
	"""Build a llama-server router preset without server-level settings."""
	lines = ["version = 1", ""]
	for record in records:
		model_id = record.model_id.strip()
		if not model_id or any(char in model_id for char in "[]\r\n"):
			continue
		lines.append(f"[{model_id}]")
		if record.kind == ModelSourceKind.HUGGING_FACE.value:
			repository = record.source.strip()
			if record.variant:
				repository = f"{repository}:{record.variant}"
			lines.append(f"hf-repo = {repository}")
		else:
			path = str(Path(record.local_path or record.source).resolve())
			lines.append(f"model = {path}")
		lines.append("")
	return "\n".join(lines)


class LlamaModelCatalog:
	"""Thread-safe JSON catalog with atomic persistence and preset export."""

	def __init__(self, directory: str | Path | None = None) -> None:
		self._directory = Path(directory) if directory else self._default_directory()
		self._manifest_path = self._directory / "models.json"
		self._preset_path = self._directory / "models.ini"
		self._lock = threading.RLock()

	@property
	def preset_path(self) -> Path:
		return self._preset_path

	def list_records(self) -> tuple[LlamaModelRecord, ...]:
		with self._lock:
			try:
				payload = json.loads(self._manifest_path.read_text(encoding="utf-8"))
			except (OSError, json.JSONDecodeError):
				return ()
			if not isinstance(payload, list):
				return ()
			return tuple(
				LlamaModelRecord(**item)
				for item in payload
				if isinstance(item, dict) and item.get("model_id")
			)

	def upsert(self, record: LlamaModelRecord) -> None:
		with self._lock:
			records = [item for item in self.list_records() if item.model_id != record.model_id]
			records.append(record)
			self._write_records(records)

	def remove(self, model_id: str) -> None:
		with self._lock:
			self._write_records([item for item in self.list_records() if item.model_id != model_id])

	def find(self, model_id: str) -> LlamaModelRecord | None:
		return next((item for item in self.list_records() if item.model_id == model_id), None)

	def write_preset(self) -> Path:
		with self._lock:
			self._directory.mkdir(parents=True, exist_ok=True)
			content = build_models_preset(list(self.list_records()))
			fd, temporary_name = tempfile.mkstemp(prefix="models-", suffix=".ini", dir=self._directory)
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
