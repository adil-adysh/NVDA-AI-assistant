# -*- coding: utf-8 -*-
"""Provider-neutral model import requests and source validation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re


class ModelImportError(ValueError):
	"""Raised when an import source is unsafe or unsupported."""


class ModelSourceKind(str, Enum):
	LOCAL_FILE = "local_file"
	HUGGING_FACE = "hugging_face"


_SUPPORTED_FILE_SUFFIXES = frozenset({".gguf", ".litert", ".litertlm"})
_INVALID_MODEL_ID = re.compile(r"[\x00-\x1f\\]|(?:^|/)\.\.(?:/|$)")


@dataclass(frozen=True)
class ModelImportRequest:
	"""Validated source request passed from application code to a provider."""

	source: str
	kind: ModelSourceKind
	model_id: str
	revision: str = "main"

	@property
	def is_local_file(self) -> bool:
		return self.kind is ModelSourceKind.LOCAL_FILE

	@property
	def file_suffix(self) -> str:
		return Path(self.source).suffix.lower()


def parse_model_import_source(source: str, model_id: str | None = None) -> ModelImportRequest:
	"""Parse a local file or ``repo[:revision]`` Hugging Face reference.

	Examples::

	    C:/models/model.litertlm
	    C:/models/model.gguf
	    org/model:main
	    org/model:v1.2

	A model ID may be supplied explicitly when a stable runtime ID is required.
	"""
	raw_source = str(source or "").strip()
	if not raw_source:
		raise ModelImportError("Model source cannot be empty")

	path = Path(raw_source)
	if path.suffix.lower() in _SUPPORTED_FILE_SUFFIXES:
		if not path.is_file():
			raise ModelImportError(f"Model file does not exist: {raw_source}")
		resolved_id = _validate_model_id(model_id or path.stem)
		return ModelImportRequest(raw_source, ModelSourceKind.LOCAL_FILE, resolved_id)

	if "\\" in raw_source or raw_source.startswith((".", "/")) or re.match(r"^[A-Za-z]:[/\\]", raw_source):
		raise ModelImportError("Local model files must use .gguf, .litert, or .litertlm")

	repo, separator, revision = raw_source.rpartition(":")
	if not separator:
		repo, revision = raw_source, "main"
	if not repo:
		raise ModelImportError("Hugging Face source must be formatted as repo[:revision]")
	if any(part in {"", ".", ".."} for part in repo.split("/")):
		raise ModelImportError(f"Invalid Hugging Face repository: {repo!r}")
	if not revision or any(char in revision for char in "\\\x00\r\n"):
		raise ModelImportError(f"Invalid Hugging Face revision: {revision!r}")

	default_id = f"{repo.replace('/', '-')}-{revision}" if revision != "main" else repo.replace("/", "-")
	return ModelImportRequest(
		source=repo,
		kind=ModelSourceKind.HUGGING_FACE,
		model_id=_validate_model_id(model_id or default_id),
		revision=revision,
	)


def _validate_model_id(value: str) -> str:
	model_id = str(value or "").strip()
	if not model_id or _INVALID_MODEL_ID.search(model_id):
		raise ModelImportError(f"Invalid model ID: {value!r}")
	return model_id
