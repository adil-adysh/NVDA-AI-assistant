# -*- coding: utf-8 -*-
"""Model-facing tool-name compatibility and deterministic namespacing."""
from __future__ import annotations

import hashlib
import re

MODEL_TOOL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MODEL_TOOL_NAME_MAX_LENGTH = 64
_INVALID_CHARS = re.compile(r"[^A-Za-z0-9_-]+")


def is_valid_model_tool_name(name: str) -> bool:
	return bool(MODEL_TOOL_NAME_PATTERN.fullmatch(name or ""))


def sanitize_tool_name(raw: str, *, fallback: str = "tool") -> str:
	"""Deterministically map a provider name onto the model-safe alphabet."""
	value = str(raw or "").strip()
	value = _INVALID_CHARS.sub("_", value).strip("_")
	if not value:
		value = fallback
	if len(value) <= MODEL_TOOL_NAME_MAX_LENGTH:
		return value
	return _truncate_with_hash(value, MODEL_TOOL_NAME_MAX_LENGTH)


def external_tool_name(provider_id: str, original_name: str) -> str:
	"""Build the deterministic, namespaced model-facing name for a provider tool.

	The original provider tool name is kept in the registry binding, so the
	mapping stays reversible; the hash suffix protects against truncation.
	"""
	provider = sanitize_tool_name(provider_id, fallback="provider")
	original = sanitize_tool_name(original_name, fallback="tool")
	candidate = f"mcp_{provider}__{original}"
	if len(candidate) > MODEL_TOOL_NAME_MAX_LENGTH:
		candidate = _truncate_with_hash(candidate, MODEL_TOOL_NAME_MAX_LENGTH)
	return candidate


def collision_suffix(tool_id: str) -> str:
	digest = hashlib.sha1(tool_id.encode("utf-8")).hexdigest()[:8]
	return digest


def disambiguate_model_tool_name(name: str, tool_id: str) -> str:
	"""Append a deterministic hash suffix while staying model-safe."""
	suffix = collision_suffix(tool_id)
	budget = MODEL_TOOL_NAME_MAX_LENGTH - len(suffix) - 1
	base = name[:budget] if len(name) > budget else name
	return f"{base}_{suffix}"


def native_tool_name(declared_name: str) -> str:
	"""Validate a native tool name instead of silently renaming it."""
	name = str(declared_name or "").strip()
	if not is_valid_model_tool_name(name):
		raise ValueError(
			"Tool name must match ^[A-Za-z0-9_-]{1,64}$ so model providers accept it; "
			f"got {name!r}"
		)
	return name


def _truncate_with_hash(value: str, limit: int) -> str:
	digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
	budget = max(1, limit - len(digest) - 1)
	return f"{value[:budget]}_{digest}"
