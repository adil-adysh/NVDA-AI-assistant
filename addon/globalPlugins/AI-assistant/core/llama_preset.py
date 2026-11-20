"""HF-only llama.cpp preset syntax, codec, and validation."""
from __future__ import annotations

import re
from typing import Any

from .llama_options import (
	OPTION_BY_KEY,
	SOURCE_KEYS,
	canonical_key,
	validate_options,
	validate_source_fields,
)
from .translation import _

_SECTION_RE = re.compile(r"^\[([^\]\r\n]+)\]\s*$")
_MODEL_ID_RE = re.compile(r"^[^\[\]*\r\n]+$")
_SUPPORTED_VERSION = "1"


def validate_model_id(value: object) -> str:
	model_id = str(value or "").strip()
	if not model_id or len(model_id) > 96 or not _MODEL_ID_RE.fullmatch(model_id):
		raise ValueError(_("Preset model ID must be 1-96 characters without []* or newlines."))
	return model_id


class LlamaPresetCodec:
	SUPPORTED_VERSION = _SUPPORTED_VERSION

	def validate(self, text: str) -> None:
		version = None
		current = None
		sections: dict[str, dict[str, str]] = {}
		for number, raw in enumerate(text.lstrip("\ufeff").splitlines(), 1):
			line = raw.strip()
			if not line or line.startswith(("#", ";")):
				continue
			match = _SECTION_RE.fullmatch(line)
			if match:
				current = match.group(1).strip()
				if current in sections:
					raise ValueError(_("Duplicate preset section on line {line}.").format(line=number))
				if current == "*":
					raise ValueError(_("Global [*] sections are not supported."))
				validate_model_id(current)
				sections[current] = {}
				continue
			if "=" not in line or line.startswith("["):
				raise ValueError(_("Invalid preset syntax on line {line}.").format(line=number))
			key, value = (part.strip() for part in line.split("=", 1))
			normalized = canonical_key(key)
			if current is None:
				if normalized != "version":
					raise ValueError(_("Only version is allowed before the first section on line {line}.").format(line=number))
				if version is not None:
					raise ValueError(_("Duplicate version on line {line}.").format(line=number))
				version = value
				continue
			if normalized in sections[current]:
				raise ValueError(_("Duplicate preset option on line {line}.").format(line=number))
			if normalized not in SOURCE_KEYS and normalized not in OPTION_BY_KEY:
				raise ValueError(_("Unsupported preset key on line {line}: {key}.").format(line=number, key=key))
			sections[current][normalized] = value
		if version != _SUPPORTED_VERSION:
			raise ValueError(_("Unsupported preset version: {version}. Expected version 1.").format(version=version or _("missing")))
		for section, fields in sections.items():
			source = {key: fields.pop(key) for key in list(fields) if key in SOURCE_KEYS}
			try:
				validate_source_fields(source)
				validate_options(fields)
			except ValueError as exc:
				raise ValueError(_("[{section}] {detail}").format(section=section, detail=exc)) from exc

	def encode(self, models: list[Any]) -> str:
		def identity(model):
			return str(model.get("model_id", "") if isinstance(model, dict) else model.model_id)
		result = build_models_preset(sorted(self._validated_models(models), key=identity))
		self.validate(result)
		return result

	def _validated_models(self, models):
		valid = []
		for model in models:
			try:
				validate_model_id(model.get("model_id", "") if isinstance(model, dict) else getattr(model, "model_id", ""))
			except (AttributeError, TypeError, ValueError):
				continue
			values = model if isinstance(model, dict) else vars(model)
			validate_source_fields(_source_fields(values))
			validate_options(values.get("preset_options") or {})
			valid.append(model)
		return valid


def _value(model: Any, key: str, default=None):
	return model.get(key, default) if isinstance(model, dict) else getattr(model, key, default)


def _source_fields(model: Any) -> dict[str, str]:
	fields = {
		"hf-repo": _value(model, "repo", "") or "",
		"hf-file": _value(model, "file", None) or "",
		"spec-draft-hf": _value(model, "draft_repo", None) or "",
		"spec-draft-model": _value(model, "draft_file", None) or "",
	}
	return {key: value for key, value in fields.items() if value}


def _record_source_lines(model: Any) -> list[str]:
	fields = validate_source_fields(_source_fields(model))
	order = ("hf-repo", "hf-file", "spec-draft-hf", "spec-draft-model")
	return [f"{key} = {fields[key]}" for key in order if key in fields]


def build_models_preset(models: list[Any]) -> str:
	lines = ["version = 1", ""]
	seen: set[str] = set()
	for model in models:
		try:
			model_id = validate_model_id(_value(model, "model_id", "") or "")
		except (AttributeError, TypeError, ValueError):
			continue
		if model_id in seen:
			continue
		seen.add(model_id)
		lines.append(f"[{model_id}]")
		lines.extend(_record_source_lines(model))
		options = validate_options(_value(model, "preset_options", {}) or {})
		lines.extend(f"{key} = {value}" for key, value in sorted(options.items()))
		lines.append("")
	return "\n".join(lines)


def validate_preset_model(model_id: object, repo: object, file: object = None,
		draft_repo: object = None, draft_file: object = None,
		options: dict[str, str] | None = None) -> dict[str, object]:
	"""Validate one preset record and return its canonical fields."""
	model_id = validate_model_id(model_id)
	source = validate_source_fields({
		"hf-repo": repo,
		"hf-file": file,
		"spec-draft-hf": draft_repo,
		"spec-draft-model": draft_file,
	})
	canonical = validate_options(options or {})
	if source.get("spec-draft-model") and "spec-type" not in canonical:
		raise ValueError(_("spec-draft-model requires a speculative spec-type."))
	spec_type = canonical.get("spec-type", "")
	if source.get("spec-draft-model") and not any(mode.startswith("draft-") for mode in spec_type.split(",")):
		raise ValueError(_("spec-draft-model requires a draft-* spec-type."))
	return {
		"model_id": model_id,
		"repo": source["hf-repo"],
		"file": source.get("hf-file"),
		"draft_repo": source.get("spec-draft-hf"),
		"draft_file": source.get("spec-draft-model"),
		"preset_options": canonical,
	}
