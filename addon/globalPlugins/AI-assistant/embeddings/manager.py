# -*- coding: utf-8 -*-
"""Application service for embedding model discovery and preparation."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Callable


@dataclass(frozen=True, slots=True)
class EmbeddingModelInfo:
	id: str
	name: str
	dimensions: int
	max_tokens: int
	size_mb: float
	architecture: str


def embedding_cache_dir() -> Path:
	appdata = os.getenv("APPDATA")
	base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
	path = base / "nvda" / "AIAssistant" / "models" / "embeddings"
	path.mkdir(parents=True, exist_ok=True)
	return path


class EmbeddingModelService:
	"""NVDA-side model policy port; all native work belongs to the worker."""
	def __init__(self, worker_client=None):
		self._worker_client = worker_client

	def _request(self, operation, model_id=None, *, progress=None, cancel_event=None):
		from ..core.translation import _
		client = self._worker_client
		if client is None:
			from ..plugin.worker_supervisor import get_worker_client_for_operation
			client = get_worker_client_for_operation()
		if client is None:
			raise RuntimeError(_("The local AI worker is unavailable."))
		response = client.run_job("embedding", {"operation": operation, "model_id": model_id},
			timeout=600.0, on_progress=progress, cancel_event=cancel_event)
		if not response.get("success"):
			raise RuntimeError(response.get("error_message") or _("Embedding operation failed."))
		return response

	def list_models(self) -> tuple[EmbeddingModelInfo, ...]:
		return tuple(EmbeddingModelInfo(**info) for info in self._request("list").get("models", []))

	def get_model(self, model_id: str) -> EmbeddingModelInfo:
		for model in self.list_models():
			if model.id == model_id:
				return model
		raise ValueError("Unknown embedding model: " + model_id)

	def prepare(self, model_id: str, progress: Callable[[str], None] | None = None, cancel_event=None) -> None:
		from ..core.translation import _
		if progress:
			progress(_("Preparing embedding model..."))
		from ..core.cancellation import RequestCancelled
		from ..providers.interfaces import DownloadCancelledError
		try:
			self._request("prepare", model_id, progress=progress, cancel_event=cancel_event)
		except RequestCancelled as exc:
			raise DownloadCancelledError(_("Embedding preparation cancelled.")) from exc
		if progress:
			progress(_("Embedding model is ready."))

	def is_cached(self, model_id: str) -> bool:
		return bool(self._request("cached", model_id).get("cached"))

	def delete(self, model_id: str) -> None:
		self._request("delete", model_id)


embedding_model_service = EmbeddingModelService()
