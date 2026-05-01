# -*- coding: utf-8 -*-
from __future__ import annotations

from threading import RLock
from typing import Any
from uuid import uuid4


class ResultActionStore:
	def __init__(self) -> None:
		self._lock = RLock()
		self._payloads: dict[str, dict[str, Any]] = {}

	def put(self, payload: dict[str, Any]) -> str:
		token = str(uuid4())
		with self._lock:
			self._payloads[token] = dict(payload)
		return token

	def pop(self, token: str) -> dict[str, Any] | None:
		with self._lock:
			payload = self._payloads.pop(token, None)
		return dict(payload) if payload is not None else None

	def clear(self) -> None:
		with self._lock:
			self._payloads.clear()
