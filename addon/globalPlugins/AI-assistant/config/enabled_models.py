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
			return set(data.get(provider, []))

	def is_enabled(self, provider: str, model_id: str) -> bool:
		return model_id in self.get_enabled(provider)

	def set_enabled(self, provider: str, model_id: str, enabled: bool) -> None:
		with self._lock:
			data = self._read()
			ids: list[str] = data.setdefault(provider, [])
			if enabled and model_id not in ids:
				ids.append(model_id)
			elif not enabled and model_id in ids:
				ids.remove(model_id)
			self._write(data)

	def _read(self) -> dict[str, list[str]]:
		try:
			if self._path.exists():
				raw = json.loads(self._path.read_text(encoding="utf-8"))
				if isinstance(raw, dict):
					return raw
		except (json.JSONDecodeError, OSError):
			pass
		return {}

	def _write(self, data: dict[str, list[str]]) -> None:
		self._path.parent.mkdir(parents=True, exist_ok=True)
		self._path.write_text(
			json.dumps(data, indent=2, sort_keys=True),
			encoding="utf-8",
		)
