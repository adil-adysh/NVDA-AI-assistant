# -*- coding: utf-8 -*-
"""Provider-neutral model import requests and source validation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re
from ..core.llama_model_source import validate_standalone_gguf


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
	artifact: str | None = None
	variant: str | None = None

	@property
	def is_local_file(self) -> bool:
		return self.kind is ModelSourceKind.LOCAL_FILE

	@property
	def file_suffix(self) -> str:
		return Path(self.source).suffix.lower()


def default_model_id_for_file(source: str | Path) -> str:
	"""Return the editable runtime-ID default for a selected local file."""
	return Path(source).stem


def parse_model_import_source(
	source: str,
	model_id: str | None = None,
	provider_id: str | None = None,
) -> ModelImportRequest:
	"""Parse a local file or provider-aware Hugging Face reference.

	Examples::

	    C:/models/model.litertlm
	    C:/models/model.gguf
	    org/model@main
	    org/model#file=model.litertlm
	    unsloth/Qwen3-8B-GGUF:UD-Q4_K_XL

	The colon form is deliberately interpreted as a llama.cpp variant only
	when ``provider_id`` is a llama.cpp provider.  For backwards compatibility,
	colon remains a Hugging Face revision for other providers.

	A model ID may be supplied explicitly when a stable runtime ID is required.
	"""
	raw_source = str(source or "").strip()
	is_llama = str(provider_id or "").strip().lower() in {"llama-cpp", "llama-cpp-server"}
	if not raw_source:
		raise ModelImportError("Model source cannot be empty")
	if raw_source.lower().startswith("hf://"):
		raw_source = raw_source[5:]
	fragment = ""
	if "#" in raw_source:
		raw_source, fragment = raw_source.split("#", 1)

	path = Path(raw_source)
	if not fragment and path.suffix.lower() in _SUPPORTED_FILE_SUFFIXES:
		if not path.is_file():
			raise ModelImportError(f"Model file does not exist: {raw_source}")
		if is_llama:
			validate_standalone_gguf(raw_source)
		resolved_id = _validate_model_id(model_id or path.stem)
		return ModelImportRequest(raw_source, ModelSourceKind.LOCAL_FILE, resolved_id)

	if "\\" in raw_source or raw_source.startswith((".", "/")) or re.match(r"^[A-Za-z]:[/\\]", raw_source):
		raise ModelImportError("Local model files must use .gguf, .litert, or .litertlm")

	variant = None
	repo = raw_source
	if is_llama and ":" in repo:
		repo, variant = repo.rsplit(":", 1)
		if not variant or any(char in variant for char in "\\\x00\r\n"):
			raise ModelImportError("Invalid Hugging Face variant")
	if "@" in repo:
		repo, revision = repo.rsplit("@", 1)
	elif not is_llama and ":" in repo:
		repo, revision = repo.rsplit(":", 1)
	else:
		revision = "main"
	if not repo or any(part in {"", ".", ".."} for part in repo.split("/")) or any(char in repo for char in "[]:#@\x00\r\n"):
		raise ModelImportError(f"Invalid Hugging Face repository: {repo!r}")
	selector_value = revision + (f"#{fragment}" if fragment else "")
	resolved_revision, artifact, _ = _parse_huggingface_selector(selector_value)
	if is_llama and artifact:
		validate_standalone_gguf(artifact)
	default_id = model_id or _default_model_id(repo, resolved_revision, variant)
	return ModelImportRequest(
		source=repo,
		kind=ModelSourceKind.HUGGING_FACE,
		model_id=_validate_model_id(default_id),
		revision=resolved_revision,
		artifact=artifact,
		variant=variant,
	)


def _parse_huggingface_selector(value: str) -> tuple[str, str | None, None]:
	"""Validate the revision and single artifact independently of variants."""
	revision = value
	artifact: str | None = None
	variant: str | None = None
	if "#" in revision:
		revision, fragment = revision.split("#", 1)
		if fragment.startswith("file="):
			artifact = fragment[5:]
		else:
			raise ModelImportError("Hugging Face selector must use #file=PATH")
	if not revision or any(char in revision for char in "\\\x00\r\n"):
		raise ModelImportError(f"Invalid Hugging Face revision: {revision!r}")
	if artifact is not None and (not artifact or artifact.startswith("/") or any(char in artifact for char in "\\\x00\r\n") or ".." in artifact):
		raise ModelImportError(f"Invalid Hugging Face artifact: {artifact!r}")
	return revision, artifact, variant


def _default_model_id(repo: str, revision: str, variant: str | None) -> str:
	base = repo.replace("/", "-")
	if variant:
		return f"{base}-{variant}"
	return f"{base}-{revision}" if revision != "main" else base


def _validate_model_id(value: str) -> str:
	model_id = str(value or "").strip()
	if not model_id or _INVALID_MODEL_ID.search(model_id):
		raise ModelImportError(f"Invalid model ID: {value!r}")
	return model_id
