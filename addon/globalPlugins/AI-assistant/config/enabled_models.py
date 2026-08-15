# -*- coding: utf-8 -*-
"""Persistent enabled-model preferences.

This is application persistence, not UI state.  Keeping it in ``config``
allows services and presentation adapters to share the same boundary.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path


def _store_path() -> Path:
	appdata = os.getenv("APPDATA")
	base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
	return base / "nvda" / "AIAssistant" / "enabled_models.json"


class EnabledModelsStore:
	"""Read and write enabled model IDs per provider."""

	def __init__(self) -> None:
		self._path = _store_path()
		self._lock = threading.RLock()

	def get_enabled(self, provider: str) -> set[str]:
		with self._lock:
			data = self._read()
			return self._ids(data.get(_normalize_provider(provider)))

	def is_enabled(self, provider: str, model_id: str) -> bool:
		return model_id in self.get_enabled(provider)

	def set_enabled(self, provider: str, model_id: str, enabled: bool) -> None:
		provider = _normalize_provider(provider)
		model_id = str(model_id or "").strip()
		if not provider or not model_id:
			return
		with self._lock:
			data = self._read()
			ids = self._ids(data.get(provider))
			if enabled and model_id not in ids:
				ids.add(model_id)
			elif not enabled:
				ids.discard(model_id)
			data[provider] = sorted(ids)
			self._write(data)

	@staticmethod
	def _ids(value: object) -> set[str]:
		"""Normalize persisted values and discard malformed preferences."""
		if not isinstance(value, (list, tuple, set)):
			return set()
		return {str(item).strip() for item in value if str(item).strip()}

	def _read(self) -> dict[str, list[str]]:
		try:
			if self._path.exists():
				raw = json.loads(self._path.read_text(encoding="utf-8"))
				if isinstance(raw, dict):
					return {
						_normalize_provider(provider): list(self._ids(ids))
						for provider, ids in raw.items()
						if _normalize_provider(provider)
					}
		except (json.JSONDecodeError, OSError):
			pass
		return {}

	def _write(self, data: dict[str, list[str]]) -> None:
		self._path.parent.mkdir(parents=True, exist_ok=True)
		self._path.write_text(
			json.dumps(data, indent=2, sort_keys=True),
			encoding="utf-8",
		)


def _normalize_provider(provider: object) -> str:
	"""Use one provider identity at the persistence boundary."""
	return str(provider or "").strip().lower()
