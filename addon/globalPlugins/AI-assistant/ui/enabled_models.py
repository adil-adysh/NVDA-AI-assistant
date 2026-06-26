# -*- coding: utf-8 -*-
"""Persistent store for enabled/disabled model preferences.

Lives at ``%APPDATA%/nvda/AIAssistant/enabled_models.json`` and is
shared by the model manager dialog and session state filtering.
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
    """Read / write enabled model IDs per provider.

    Thread-safe — all public methods acquire a re-entrant lock.
    """

    def __init__(self) -> None:
        self._path = _store_path()
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_enabled(self, provider: str) -> set[str]:
        """Return the set of enabled ``model_id`` values for *provider*."""
        with self._lock:
            data = self._read()
            return set(data.get(provider, []))

    def is_enabled(self, provider: str, model_id: str) -> bool:
        """Return ``True`` if *model_id* is enabled for *provider*."""
        return model_id in self.get_enabled(provider)

    def set_enabled(self, provider: str, model_id: str, enabled: bool) -> None:
        """Enable or disable *model_id* for *provider*."""
        with self._lock:
            data = self._read()
            ids: list[str] = data.setdefault(provider, [])
            if enabled and model_id not in ids:
                ids.append(model_id)
            elif not enabled and model_id in ids:
                ids.remove(model_id)
            self._write(data)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

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
