# -*- coding: utf-8 -*-
"""Lazy adapter for the Rust/Candle embedding extension."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any


class CandleEmbeddingAdapter:
	"""Implement the context reducer's embedder port without hard coupling.

	The extension is imported only on first embedding request.  This keeps NVDA
	startup and all non-text/image use cases independent of the optional native
	component.
	"""

	def __init__(self, model_id: str | None = None) -> None:
		self._model_id = model_id or "harrier-oss-v1-270m"
		self._engine: Any | None = None

	def _cache_dir(self) -> str:
		from .manager import embedding_cache_dir
		return str(embedding_cache_dir())

	def _sync_selected_model(self) -> None:
		"""Apply a settings change on the next request without restarting NVDA."""
		try:
			from ..config.settings import get_embedding_model
			selected = get_embedding_model()
		except Exception:
			return
		if selected and selected != self._model_id:
			self._model_id = selected
			self._engine = None

	@property
	def model_key(self) -> str:
		self._sync_selected_model()
		return f"candle:{self._model_id}"

	def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
		self._sync_selected_model()
		if not texts:
			return ()
		if self._engine is None:
			try:
				import embedding_engine
			except ImportError as error:
				raise RuntimeError("The optional embedding engine is unavailable") from error
			self._engine = embedding_engine.EmbeddingEngine(self._model_id, self._cache_dir())
		return tuple(tuple(float(value) for value in vector) for vector in self._engine.embed_batch(list(texts)))

	def embed_query(self, query: str, instruction: str) -> Sequence[float]:
		"""Embed an instructed query while leaving document text untouched.

		Harrier's model card explicitly requires a one-sentence instruction on
		queries and explicitly forbids adding it to documents.  Other embedding
		models use the raw query until they publish an equivalent contract.
		"""
		self._sync_selected_model()
		if "harrier" in self._model_id.lower():
			query = f"Instruct: {instruction}\nQuery: {query}"
		return self.embed((query,))[0]
