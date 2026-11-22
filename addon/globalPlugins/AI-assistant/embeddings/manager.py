# -*- coding: utf-8 -*-
"""Application service for embedding model discovery and preparation."""
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Callable


@dataclass(frozen=True, slots=True)
class EmbeddingModelInfo:
	id: str
	name: str
	dimensions: int
	max_tokens: int
	size_mb: float
	architecture: str


_cache_epochs: dict[str, int] = {}
_epoch_lock = Lock()


def embedding_cache_epoch(model_id: str) -> int:
	with _epoch_lock:
		return _cache_epochs.get(model_id, 0)


def _advance_cache_epoch(model_id: str) -> None:
	with _epoch_lock:
		_cache_epochs[model_id] = _cache_epochs.get(model_id, 0) + 1


class EmbeddingModelService:
	"""NVDA-side model policy port; all native work belongs to the worker."""
	def __init__(self, worker_client=None):
		self._worker_client = worker_client

	def _request(self, operation, model_id=None, *, progress=None, cancel_event=None, **options):
		from ..core.translation import _
		client = self._worker_client
		if client is None:
			from ..plugin.worker_supervisor import get_worker_client_for_operation
			client = get_worker_client_for_operation()
		if client is None:
			raise RuntimeError(_("The local AI worker is unavailable."))
		response = client.run_job("embedding", {"operation": operation, "model_id": model_id, **options},
			timeout=600.0, on_progress=progress, cancel_event=cancel_event)
		if not response.get("success"):
			raise RuntimeError(response.get("error_message") or _("Embedding operation failed."))
		return response

	def list_models(self) -> tuple[EmbeddingModelInfo, ...]:
		return tuple(EmbeddingModelInfo(**info) for info in self._request("list").get("models", []))

	def catalog(self, *, cancel_event=None) -> tuple[tuple[EmbeddingModelInfo, ...], dict[str, bool]]:
		response = self._request("list", include_cache=True, cancel_event=cancel_event)
		return tuple(EmbeddingModelInfo(**info) for info in response["models"]), response["cache"]

	def get_model(self, model_id: str) -> EmbeddingModelInfo:
		for model in self.list_models():
			if model.id == model_id:
				return model
		raise ValueError("Unknown embedding model: " + model_id)

	def prepare(self, model_id: str, progress: Callable[[str], None] | None = None, cancel_event=None) -> None:
		from ..core.translation import _
		from ..core.cancellation import RequestCancelled
		from ..providers.interfaces import DownloadCancelledError
		def report(stage: str) -> None:
			if progress is None:
				return
			if stage == "embedding.download":
				progress(_("Downloading embedding model files if needed..."))
			elif stage == "embedding.validate":
				progress(_("Loading and validating the embedding model..."))

		try:
			self._request("prepare", model_id, progress=report if progress else None, cancel_event=cancel_event)
		except RequestCancelled as exc:
			raise DownloadCancelledError(_("Embedding preparation cancelled.")) from exc
		_advance_cache_epoch(model_id)
		if progress:
			progress(_("Embedding model is ready."))

	def is_cached(self, model_id: str) -> bool:
		return bool(self._request("cached", model_id).get("cached"))

	def delete(self, model_id: str) -> None:
		self._request("delete", model_id)
		_advance_cache_epoch(model_id)


embedding_model_service = EmbeddingModelService()
