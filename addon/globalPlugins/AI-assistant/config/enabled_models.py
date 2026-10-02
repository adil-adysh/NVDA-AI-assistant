# -*- coding: utf-8 -*-
"""Persistent model visibility preferences.

This is application persistence, not UI state.  Keeping it in ``config``
allows services and presentation adapters to share the same boundary.

Visibility preferences store explicitly disabled models per provider.
Newly discovered models are visible by default.  Explicitly disabled models
remain disabled until the user explicitly re-enables them.  Disabling all
models is a durable preference and will not revert to showing all models.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterable
from pathlib import Path


def _store_path() -> Path:
	appdata = os.getenv("APPDATA")
	base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
	return base / "nvda" / "AIAssistant" / "model_visibility.json"


def _legacy_store_path() -> Path:
	appdata = os.getenv("APPDATA")
	base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
	return base / "nvda" / "AIAssistant" / "enabled_models.json"


def _normalize_provider(provider: object) -> str:
	"""Use one provider identity at the persistence boundary."""
	return str(provider or "").strip().lower()


class ModelVisibilityStore:
	"""Read and write model visibility preferences per provider."""

	def __init__(
		self,
		path: Path | None = None,
		legacy_path: Path | None = None,
	) -> None:
		self._path = path or _store_path()
		self._legacy_path = legacy_path or _legacy_store_path()
		self._lock = threading.RLock()

	def is_model_visible(self, provider: str, model_id: str) -> bool:
		"""Return True if *model_id* is visible (not explicitly disabled)."""
		norm_provider = _normalize_provider(provider)
		norm_model = str(model_id or "").strip()
		if not norm_provider or not norm_model:
			return False
		with self._lock:
			disabled = self.get_disabled_models(norm_provider)
			return norm_model not in disabled

	def set_model_visible(self, provider: str, model_id: str, visible: bool) -> None:
		"""Set whether *model_id* is visible for *provider*."""
		norm_provider = _normalize_provider(provider)
		norm_model = str(model_id or "").strip()
		if not norm_provider or not norm_model:
			return
		with self._lock:
			data = self._read()
			provider_entry = data.setdefault(norm_provider, {"disabled": set()})
			disabled_set = provider_entry.setdefault("disabled", set())
			if visible:
				disabled_set.discard(norm_model)
			else:
				disabled_set.add(norm_model)
			self._write(data)

	def get_disabled_models(self, provider: str) -> set[str]:
		"""Return the set of explicitly disabled model IDs for *provider*."""
		norm_provider = _normalize_provider(provider)
		if not norm_provider:
			return set()
		with self._lock:
			data = self._read()
			entry = data.get(norm_provider, {})
			return set(entry.get("disabled", set()))

	def get_visible_models(self, provider: str, candidates: Iterable[str]) -> tuple[str, ...]:
		"""Filter *candidates* to only those not explicitly disabled."""
		norm_provider = _normalize_provider(provider)
		if not norm_provider:
			return ()
		with self._lock:
			disabled = self.get_disabled_models(norm_provider)
			visible: list[str] = []
			for m in candidates:
				clean_id = str(m or "").strip()
				if clean_id and clean_id not in disabled:
					visible.append(clean_id)
			return tuple(visible)

	def clear(self, provider: str | None = None) -> None:
		"""Reset preferences for *provider* (or all providers if None)."""
		with self._lock:
			if provider is None:
				self._write({})
			else:
				data = self._read()
				data.pop(_normalize_provider(provider), None)
				self._write(data)

	# ------------------------------------------------------------------
	# Backward-compatible aliases for EnabledModelsStore API
	# ------------------------------------------------------------------

	def is_enabled(self, provider: str, model_id: str) -> bool:
		return self.is_model_visible(provider, model_id)

	def set_enabled(self, provider: str, model_id: str, enabled: bool) -> None:
		self.set_model_visible(provider, model_id, enabled)

	def get_enabled(self, provider: str, candidates: Iterable[str] | None = None) -> set[str]:
		"""Return enabled model IDs.

		When *candidates* is supplied, returns all candidates not explicitly
		disabled.  When *candidates* is omitted, returns an empty set if all
		models are disabled, or the inverted set if known.
		"""
		if candidates is not None:
			return set(self.get_visible_models(provider, candidates))
		# Legacy compatibility without candidates
		disabled = self.get_disabled_models(provider)
		with self._lock:
			data = self._read()
			entry = data.get(_normalize_provider(provider), {})
			# If migration or explicit enabled list exists, return it
			explicit = entry.get("explicitly_enabled", set())
			if explicit:
				return set(explicit) - disabled
		return set()

	# ------------------------------------------------------------------
	# Persistence & Migration
	# ------------------------------------------------------------------

	def _read(self) -> dict[str, dict[str, set[str]]]:
		"""Read visibility preferences, migrating from legacy store if needed."""
		if self._path.exists():
			try:
				raw = json.loads(self._path.read_text(encoding="utf-8"))
				if isinstance(raw, dict):
					providers_data = raw.get("providers", raw) if "providers" in raw else raw
					result: dict[str, dict[str, set[str]]] = {}
					for p, val in providers_data.items():
						norm_p = _normalize_provider(p)
						if not norm_p:
							continue
						if isinstance(val, dict):
							disabled = {str(x).strip() for x in val.get("disabled", []) if str(x).strip()}
							explicit = {str(x).strip() for x in val.get("explicitly_enabled", []) if str(x).strip()}
							result[norm_p] = {"disabled": disabled, "explicitly_enabled": explicit}
						elif isinstance(val, list):
							# List in visibility file treated as disabled list
							disabled = {str(x).strip() for x in val if str(x).strip()}
							result[norm_p] = {"disabled": disabled}
					return result
			except (json.JSONDecodeError, OSError):
				pass

		# Fall back to legacy enabled_models.json migration
		if self._legacy_path.exists():
			try:
				raw = json.loads(self._legacy_path.read_text(encoding="utf-8"))
				if isinstance(raw, dict):
					migrated: dict[str, dict[str, set[str]]] = {}
					for p, val in raw.items():
						norm_p = _normalize_provider(p)
						if not norm_p or not isinstance(val, list):
							continue
						enabled_ids = {str(x).strip() for x in val if str(x).strip()}
						# If legacy had an empty list, all models were explicitly disabled
						# We record that legacy preferences had these specific enabled IDs
						migrated[norm_p] = {"disabled": set(), "explicitly_enabled": enabled_ids}
					return migrated
			except (json.JSONDecodeError, OSError):
				pass

		return {}

	def _write(self, data: dict[str, dict[str, set[str]]]) -> None:
		self._path.parent.mkdir(parents=True, exist_ok=True)
		serializable = {
			"version": 1,
			"providers": {
				p: {
					"disabled": sorted(val.get("disabled", set())),
					**({"explicitly_enabled": sorted(val["explicitly_enabled"])} if val.get("explicitly_enabled") else {}),
				}
				for p, val in sorted(data.items())
			},
		}
		self._path.write_text(
			json.dumps(serializable, indent=2, sort_keys=True),
			encoding="utf-8",
		)


# Backward-compatible alias
EnabledModelsStore = ModelVisibilityStore
