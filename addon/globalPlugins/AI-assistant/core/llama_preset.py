"""Pure llama router preset reconciliation shared by NVDA and worker."""
from pathlib import Path
import re
from typing import Any
from .translation import _
from .llama_options import validate_options
from .llama_companions import companion_options

_SECTION_RE = re.compile(r"^\[([^\]\r\n]+)\]\s*$")


class LlamaPresetCodec:
	"""Versioned supported syntax; opaque user options remain untouched."""
	SUPPORTED_VERSION = "1"

	def validate(self, text: str) -> None:
		version = None
		section = None
		sections = set()
		keys = set()
		for number, raw in enumerate(text.lstrip("\ufeff").splitlines(), 1):
			line = raw.strip()
			if not line or line.startswith(("#", ";")):
				continue
			match = _SECTION_RE.fullmatch(line)
			if match:
				section = match.group(1).strip()
				if not section or section in sections or any(ord(char) < 32 for char in section):
					raise ValueError(_("Duplicate or empty llama.cpp preset section on line {line}.").format(line=number))
				sections.add(section)
				keys = set()
				continue
			if "=" not in line or line.startswith("["):
				raise ValueError(_("Invalid llama.cpp preset syntax on line {line}.").format(line=number))
			key, value = (value.strip() for value in line.split("=", 1))
			key = key.lower()
			if key in keys:
				raise ValueError(_("Duplicate llama.cpp preset option on line {line}.").format(line=number))
			keys.add(key)
			if section is None and key == "version":
				version = value
			if key == "ctx-size":
				try:
					if int(value) < 0:
						raise ValueError()
				except ValueError as exc:
					raise ValueError(_("Invalid llama.cpp context size on line {line}.").format(line=number)) from exc
		if version != self.SUPPORTED_VERSION:
			raise ValueError(_("Unsupported llama.cpp preset version: {version}. Expected version 1.").format(version=version or _("missing")))

	def _validated_models(self, models):
		valid = []
		for model in models:
			identity = model.get("model_id", "") if isinstance(model, dict) else getattr(model, "model_id", "")
			if not str(identity).strip() or any(char in str(identity) for char in "[]*\r\n"):
				continue
			values = model if isinstance(model, dict) else vars(model)
			for key in ("source", "variant", "local_path", "artifact", "hf_repo", "hf-repo"):
				value = values.get(key)
				if value is not None and any(ord(char) < 32 for char in str(value)):
					raise ValueError(_("Model preset values must be single-line strings."))
			valid.append(model)
		return valid

	def encode(self, models: list[Any]) -> str:
		def identity(model):
			return str(model.get("model_id", "") if isinstance(model, dict) else model.model_id)
		result = build_models_preset(sorted(self._validated_models(models), key=identity))
		self.validate(result)
		return result

	def reconcile(self, text: str, models: list[Any], *, removed_ids=()) -> str:
		if text.strip():
			self.validate(text)
		for model_id in sorted(removed_ids):
			text = self.remove(text, model_id)
		result = merge_models_preset(text, sorted(self._validated_models(models), key=lambda m: str(m.get("model_id", "") if isinstance(m, dict) else m.model_id)))
		self.validate(result)
		return result

	def remove(self, text: str, model_id: str) -> str:
		lines = text.splitlines()
		output = []
		keep = True
		for line in lines:
			match = _SECTION_RE.fullmatch(line.strip())
			if match:
				keep = match.group(1).strip() != model_id
			if keep:
				output.append(line)
		return "\n".join(output).rstrip() + "\n"

def _record_source_lines(model: dict[str, Any] | Any) -> list[str]:
	if isinstance(model, dict):
		kind = model.get("kind", "")
		source = str(model.get("source", "")).strip()
		variant = model.get("variant")
		local_path = model.get("local_path")
		artifact = model.get("artifact") or model.get("hf-file")
		hf_repo = model.get("hf_repo") or model.get("hf-repo")
	else:
		kind = getattr(model, "kind", "")
		source = str(getattr(model, "source", "")).strip()
		variant = getattr(model, "variant", None)
		local_path = getattr(model, "local_path", None)
		artifact = getattr(model, "artifact", None)
		hf_repo = getattr(model, "hf_repo", None)

	if hf_repo:
		clean_hf_repo = re.sub(r"[\r\n]+", "", str(hf_repo)).strip()
		if clean_hf_repo:
			return [f"hf-repo = {clean_hf_repo}"] + ([f"hf-file = {re.sub(chr(13) + '|' + chr(10), '', str(artifact))}"] if artifact else [])
	if kind == "hugging_face" or source.startswith("hf://"):
		clean_source = re.sub(r"[\r\n]+", "", source).strip()
		repo = clean_source.removeprefix("hf://").strip()
		if variant:
			clean_variant = re.sub(r"[\r\n]+", "", str(variant)).strip()
			if clean_variant:
				repo = f"{repo}:{clean_variant}"
		if repo:
			return [f"hf-repo = {repo}"] + ([f"hf-file = {re.sub(chr(13) + '|' + chr(10), '', str(artifact))}"] if artifact else [])
	raw_target = str(local_path or source)
	clean_target = re.sub(r"[\r\n]+", "", raw_target).strip()
	if not clean_target:
		return []
	try:
		path = str(Path(clean_target).resolve())
	except Exception:
		path = clean_target
	return [f"model = {path}"]


def build_models_preset(models: list[Any]) -> str:
	"""Build a llama-server router preset from model records."""
	lines = ["version = 1", ""]
	for m in models:
		m_id = m.get("model_id") if isinstance(m, dict) else getattr(m, "model_id", "")
		m_id = str(m_id or "").strip()
		if not m_id or any(char in m_id for char in "[]*\r\n"):
			continue
		lines.append(f"[{m_id}]")
		lines.extend(_new_record_lines(m))
		lines.append("")
	return "\n".join(lines)


def _new_record_lines(model: Any) -> list[str]:
	lines = _record_source_lines(model)
	values = model if isinstance(model, dict) else vars(model)
	options = validate_options(values.get("preset_options") or {})
	options.update(companion_options(values.get("companions")))
	context = values.get("context_window")
	if context is not None and "ctx-size" not in options:
		if int(context) <= 0:
			raise ValueError(_("Model context size must be positive."))
		lines.append(f"ctx-size = {int(context)}")
	if "thinking" in (values.get("capabilities") or ()) and "reasoning" not in options and "reasoning-format" not in options:
		lines.append("reasoning = on")
	lines.extend(f"{key} = {value}" for key, value in sorted(options.items()))
	return lines


def merge_models_preset(text: str, models: list[Any]) -> str:
	"""Reconcile model sources while preserving preset comments and options."""
	if not text.strip():
		return build_models_preset(models)
	lines = text.splitlines()
	sections: list[tuple[str, int, int]] = []
	for index, line in enumerate(lines):
		match = _SECTION_RE.match(line.strip())
		if match:
			if sections:
				sections[-1] = (sections[-1][0], sections[-1][1], index)
			sections.append((match.group(1).strip(), index, len(lines)))

	managed: dict[str, Any] = {}
	for m in models:
		m_id = m.get("model_id") if isinstance(m, dict) else getattr(m, "model_id", "")
		m_id_str = str(m_id or "").strip()
		if m_id_str and not any(char in m_id_str for char in "[]*\r\n"):
			managed[m_id_str] = m

	output = list(lines)
	for section, start, end in reversed(sections):
		m = managed.get(section)
		if m is None or section == "*":
			continue
		body = output[start + 1 : end]
		body = [line for line in body if not re.match(r"^\s*(?:model|hf-repo|hf-file)\s*=", line, re.I)]
		body = _record_source_lines(m) + body
		output[start + 1 : end] = body

	existing = {section for section, _, _ in sections}
	for m in models:
		m_id = m.get("model_id") if isinstance(m, dict) else getattr(m, "model_id", "")
		m_id_str = str(m_id or "").strip()
		if not m_id_str or any(char in m_id_str for char in "[]*\r\n") or m_id_str in existing:
			continue
		while output and not output[-1].strip():
			output.pop()
		output.extend(["", f"[{m_id_str}]", *_new_record_lines(m)])
	return "\n".join(output).rstrip() + "\n"

