# -*- coding: utf-8 -*-
"""Lazy adapter for the Rust/Candle embedding extension."""
from __future__ import annotations

from collections.abc import Sequence


class CandleEmbeddingAdapter:
	"""Implement the context reducer's embedder port without hard coupling.

	The worker is started only on the first embedding request.  This keeps NVDA
	startup and all non-text/image use cases independent of the optional native
	component.
	"""

	def __init__(self, model_id: str | None = None, worker_client=None, *, cache_epoch: int = 0) -> None:
		self._model_id = model_id
		self._worker_client = worker_client
		self._cache_epoch = cache_epoch

	def _selected_model(self) -> str:
		from ..config.defaults import DEFAULT_EMBEDDING_MODEL
		from ..config.settings import get_embedding_model

		return get_embedding_model() or DEFAULT_EMBEDDING_MODEL

	def for_retrieval(self) -> CandleEmbeddingAdapter:
		"""Pin the model and cache identity for the entire retrieval."""
		if self._model_id is not None:
			return self
		from .manager import embedding_cache_epoch

		model_id = self._selected_model()
		return CandleEmbeddingAdapter(model_id, self._worker_client, cache_epoch=embedding_cache_epoch(model_id))

	@property
	def model_key(self) -> str:
		retrieval = self.for_retrieval()
		return f"candle:{retrieval._model_id}:{retrieval._cache_epoch}"

	def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
		if self._model_id is None:
			return self.for_retrieval().embed(texts)
		if not texts:
			return ()
		from ..core.translation import _
		client = self._worker_client
		if client is None:
			from ..plugin.worker_supervisor import get_worker_client_for_operation
			client = get_worker_client_for_operation()
		if client is None:
			raise RuntimeError(_("The local AI worker is unavailable."))
		vectors = []
		for offset in range(0, len(texts), 256):
			batch = [text[:4096] for text in texts[offset:offset + 256]]
			response = client.run_job("embedding", {"operation": "embed", "model_id": self._model_id,
				"texts": batch}, timeout=15.0)
			if not response.get("success"):
				raise RuntimeError(response.get("error_message") or _("Embedding operation failed."))
			result = response.get("vectors", [])
			if len(result) != len(batch):
				raise RuntimeError(_("The embedding worker returned an incomplete batch."))
			vectors.extend(result)
		return tuple(tuple(float(value) for value in vector) for vector in vectors)

	def format_query(self, query: str, instruction: str) -> str:
		"""Apply the selected model's query instruction without changing documents."""
		if self._model_id is None:
			return self.for_retrieval().format_query(query, instruction)
		if self._model_id == "harrier-oss-v1-270m":
			return f"Instruct: {instruction}\nQuery: {query}"
		return query

	def embed_query(self, query: str, instruction: str) -> Sequence[float]:
		retrieval = self.for_retrieval()
		return retrieval.embed((retrieval.format_query(query, instruction),))[0]
