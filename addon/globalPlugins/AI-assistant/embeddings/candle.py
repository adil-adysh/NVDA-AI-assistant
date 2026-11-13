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

	def __init__(self, model_id: str | None = None, worker_client=None) -> None:
		self._model_id = model_id or "harrier-oss-v1-270m"
		self._worker_client = worker_client

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

	@property
	def model_key(self) -> str:
		self._sync_selected_model()
		return f"candle:{self._model_id}"

	def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
		self._sync_selected_model()
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
			batch = list(texts[offset:offset + 256])
			response = client.run_job("embedding", {"operation": "embed", "model_id": self._model_id,
				"texts": batch}, timeout=600.0)
			if not response.get("success"):
				raise RuntimeError(response.get("error_message") or _("Embedding operation failed."))
			result = response.get("vectors", [])
			if len(result) != len(batch):
				raise RuntimeError(_("The embedding worker returned an incomplete batch."))
			vectors.extend(result)
		return tuple(tuple(float(value) for value in vector) for vector in vectors)

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
