# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import tempfile
import yaml
from pathlib import Path
from typing import Any

from logHandler import log

from .defaults import DEFAULT_CONFIG_PATH
from .store import ConfigStore
from ..utils.crypto import decrypt_value, encrypt_value, is_encrypted, is_sensitive_key


class YamlConfigStore(ConfigStore):
	"""YAML-backed store for AI assistant configuration.

	Sensitive values (API keys / tokens) are transparently encrypted using
	Windows DPAPI before being written to disk, and decrypted on load.
	"""

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
			log.exception("Error loading configuration from %s", self._file_path)
			self._data = {}

		# Decrypt any encrypted values (transparent to callers).
		self._decrypt_sensitive()

	def save(self) -> None:
		self._file_path.parent.mkdir(parents=True, exist_ok=True)
		fd, temp_path = tempfile.mkstemp(
			prefix=self._file_path.stem, suffix=self._file_path.suffix, dir=self._file_path.parent
		)
		try:
			# Write an encrypted copy – never mutate self._data.
			write_data = self._encrypt_sensitive(self._data)
			with os.fdopen(fd, "w", encoding="utf-8") as config_file:
				yaml.safe_dump(
					{self._section_name: write_data},
					config_file,
					sort_keys=False,
					default_flow_style=False,
				)
			Path(temp_path).replace(self._file_path)
		finally:
			try:
				Path(temp_path).unlink(missing_ok=True)
			except Exception:
				pass

	def get(self, key: str, default: Any) -> Any:
		return self._data.get(key, default)

	def set(self, key: str, value: Any) -> None:
		self._data[key] = value
		self.save()

	def set_many(self, values: dict[str, Any]) -> None:
		self._data.update(values)
		self.save()

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _decrypt_sensitive(self) -> None:
		"""Decrypt any encrypted values in ``self._data`` in-place."""
		for key, value in list(self._data.items()):
			if is_sensitive_key(key) and isinstance(value, str) and is_encrypted(value):
				self._data[key] = decrypt_value(value)

	@staticmethod
	def _encrypt_sensitive(data: dict[str, Any]) -> dict[str, Any]:
		"""Return a shallow copy of *data* with sensitive values encrypted."""
		result = dict(data)
		for key, value in result.items():
			if is_sensitive_key(key) and isinstance(value, str) and value:
				# Encrypt plaintext values (migration) or re-encrypt already-encrypted ones.
				if not is_encrypted(value):
					result[key] = encrypt_value(value)
				# Already-encrypted values are left as-is (set() always writes plaintext,
				# so this path is only hit for values that were never read after load).
		return result
