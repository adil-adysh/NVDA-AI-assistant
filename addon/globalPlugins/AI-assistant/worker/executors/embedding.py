# -*- coding: utf-8 -*-
"""Application service for embedding model discovery and preparation."""
from __future__ import annotations

from dataclasses import dataclass, asdict
import threading
import os
from pathlib import Path
from typing import Any, Callable


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
	"""Own model lifecycle without exposing native runtime details to UI."""

	def list_models(self) -> tuple[EmbeddingModelInfo, ...]:
		embedding_engine = self._load_native_engine()
		models: list[EmbeddingModelInfo] = []
		for model_id in sorted(embedding_engine.EmbeddingEngine.available_models()):
			info = embedding_engine.EmbeddingEngine.model_info(model_id)
			if not isinstance(info, dict):
				continue
			models.append(
				EmbeddingModelInfo(
					id=model_id,
					name=str(info.get("name", model_id)),
					dimensions=int(info["dimensions"]),
					max_tokens=int(info["max_tokens"]),
					size_mb=float(info.get("model_size_mb", 0.0)),
					architecture=str(info.get("architecture", "")),
				)
			)
		return tuple(models)

	def get_model(self, model_id: str) -> EmbeddingModelInfo:
		for model in self.list_models():
			if model.id == model_id:
				return model
		raise ValueError(f"Unknown embedding model: {model_id}")

	def prepare(self, model_id: str, progress: Callable[[str], None] | None = None) -> None:
		model = self.get_model(model_id)
		if progress:
			progress(f"Preparing {model.name}…")
		embedding_engine = self._load_native_engine()
		engine = self._create_engine(embedding_engine, model.id)
		# The native runtime owns download and artifact validation.
		prepare = getattr(engine, "prepare", None)
		if not callable(prepare):
			raise RuntimeError("The installed embedding engine does not support model preparation")
		prepare()
		if progress:
			progress(f"{model.name} is ready.")

	def is_cached(self, model_id: str) -> bool:
		self.get_model(model_id)
		embedding_engine = self._load_native_engine()
		engine = self._create_engine(embedding_engine, model_id)
		is_cached = getattr(engine, "is_cached", None)
		if not callable(is_cached):
			raise RuntimeError("The installed embedding engine does not support cache inspection")
		return bool(is_cached())

	def delete(self, model_id: str) -> None:
		self.get_model(model_id)
		embedding_engine = self._load_native_engine()
		delete_cached = getattr(embedding_engine.EmbeddingEngine, "delete_cached", None)
		if not callable(delete_cached):
			raise RuntimeError("The installed embedding engine does not support cache deletion")
		delete_cached(model_id, str(embedding_cache_dir()))

	@staticmethod
	def _load_native_engine() -> Any:
		try:
			import embedding_engine
		except ImportError as error:
			raise RuntimeError("The embedding engine is not installed") from error
		return embedding_engine

	def _create_engine(self, embedding_engine: Any, model_id: str) -> Any:
		"""Construct old and new native engine APIs."""
		try:
			return embedding_engine.EmbeddingEngine(model_id, str(embedding_cache_dir()))
		except TypeError:
			# Current versions manage their own Hugging Face cache and accept only
			# the model ID.
			return embedding_engine.EmbeddingEngine(model_id)



# All engine/cache operations are serialized; loading a replacement drops the old engine.

try:
	from ...core.job.dto import JobResult, JobStatus
except ImportError:
	from core.job.dto import JobResult, JobStatus

_lock = threading.Lock()
_service = EmbeddingModelService()
_engine = None
_model = None


def execute_embedding_job(spec, token):
	global _engine, _model
	acquired = False
	try:
		while not _lock.acquire(timeout=0.05):
			token.check_cancelled()
		acquired = True
		token.check_cancelled()
		operation = spec.payload.get("operation")
		model = str(spec.payload.get("model_id", ""))
		data = {"success": True}
		if operation == "list":
			data["models"] = [asdict(info) for info in _service.list_models()]
		elif operation == "prepare":
			_service.prepare(model)
		elif operation == "cached":
			data["cached"] = _service.is_cached(model)
		elif operation == "delete":
			if _model == model:
				_engine, _model = None, None
			_service.delete(model)
		elif operation == "embed":
			texts = spec.payload.get("texts")
			if not isinstance(texts, list) or len(texts) > 256 or any(not isinstance(text, str) for text in texts):
				raise ValueError("Invalid embedding batch")
			if _engine is None or model != _model:
				_service.get_model(model)
				_engine = _service._create_engine(_service._load_native_engine(), model)
				_model = model
			vectors = []
			for offset in range(0, len(texts), 8):
				token.check_cancelled()
				vectors.extend(_engine.embed_batch(texts[offset:offset + 8]))
			data["vectors"] = vectors
		else:
			raise ValueError("Unknown embedding operation")
		token.check_cancelled()
		return JobResult(job_id=spec.job_id, status=JobStatus.COMPLETED,
			result_data=data, generation=spec.generation)
	finally:
		if acquired:
			_lock.release()
