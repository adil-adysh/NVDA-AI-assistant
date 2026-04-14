# -*- coding: utf-8 -*-
from __future__ import annotations

import yaml
from pathlib import Path
from typing import Any

from .defaults import DEFAULT_CONFIG_PATH
from .store import ConfigStore


class YamlConfigStore(ConfigStore):
	"""YAML-backed store for AI assistant configuration."""

	def __init__(self, path: str | Path | None = None, section_name: str = "aiAssistant") -> None:
		self._file_path = Path(path or DEFAULT_CONFIG_PATH)
		self._section_name = section_name
		self._data: dict[str, Any] = {}
		self.load()

	def load(self) -> None:
		try:
			with self._file_path.open("r", encoding="utf-8") as config_file:
				raw = yaml.safe_load(config_file)
			if isinstance(raw, dict):
				section = raw.get(self._section_name)
				self._data = section if isinstance(section, dict) else {}
			else:
				self._data = {}
		except FileNotFoundError:
			self._data = {}
		except Exception:
			self._data = {}

	def save(self) -> None:
		self._file_path.parent.mkdir(parents=True, exist_ok=True)
		with self._file_path.open("w", encoding="utf-8") as config_file:
			yaml.safe_dump(
				{self._section_name: self._data},
				config_file,
				sort_keys=False,
				default_flow_style=False,
			)

	def get(self, key: str, default: Any) -> Any:
		return self._data.get(key, default)

	def set(self, key: str, value: Any) -> None:
		self._data[key] = value
		self.save()

	def set_many(self, values: dict[str, Any]) -> None:
		self._data.update(values)
		self.save()
