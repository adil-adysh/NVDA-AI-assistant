# -*- coding: utf-8 -*-
"""Application service for embedding model discovery and preparation."""
from __future__ import annotations

from dataclasses import dataclass, asdict
import os
from pathlib import Path
from typing import Any, Callable


_MAX_INPUT_TOKENS = 512


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
	return path


class EmbeddingModelService:
	"""Own model lifecycle without exposing native runtime details to UI."""

	def __init__(self) -> None:
		self._engine: Any = None
		self._model: EmbeddingModelInfo | None = None

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
					max_tokens=min(int(info["max_tokens"]), _MAX_INPUT_TOKENS),
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

	def engine_for(self, model_id: str) -> Any:
		if self._model is None or self._model.id != model_id:
			model = self.get_model(model_id)
			self._engine = self._create_engine(self._load_native_engine(), model_id)
			self._model = model
		return self._engine

	def prepare(
		self, model_id: str, check_cancelled: Callable[[], None] = lambda: None,
		progress: Callable[[str], None] | None = None,
	) -> None:
		engine = self.engine_for(model_id)
		if progress:
			progress("embedding.download")
		engine.download(check_cancelled)
		check_cancelled()
		if progress:
			progress("embedding.validate")
		engine.validate()
		check_cancelled()

	def embed(self, model_id: str, texts: list[str], check_cancelled: Callable[[], None]) -> list:
		engine = self.engine_for(model_id)
		if not engine.is_cached():
			raise RuntimeError("The selected embedding model needs to be downloaded")
		vectors = []
		for text in texts:
			check_cancelled()
			vectors.append(engine.embed(text))
		return vectors

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
		if self._model is not None and self._model.id == model_id:
			self._engine, self._model = None, None
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
		if not hasattr(embedding_engine, "EmbeddingEngine"):
			raise RuntimeError("The embedding engine is not installed")
		return embedding_engine

	@staticmethod
	def _create_engine(embedding_engine: Any, model_id: str) -> Any:
		return embedding_engine.EmbeddingEngine(
			model_id, str(embedding_cache_dir()), max_input_tokens=_MAX_INPUT_TOKENS, offline=True,
		)


try:
	from ...core.job.dto import JobProgress, JobResult, JobStatus
except ImportError:
	from core.job.dto import JobProgress, JobResult, JobStatus

# The server's embedding lane serializes model, inference, and cache operations.
_service = EmbeddingModelService()


def execute_embedding_job(spec, token, emit_progress):
	token.check_cancelled()
	operation = spec.payload.get("operation")
	model = str(spec.payload.get("model_id", ""))
	data = {"success": True}
	if operation == "list":
		models = _service.list_models()
		data["models"] = [asdict(info) for info in models]
		if spec.payload.get("include_cache"):
			data["cache"] = {info.id: _service.is_cached(info.id) for info in models}
	elif operation == "prepare":
		def progress(stage: str) -> None:
			emit_progress(JobProgress(
				job_id=spec.job_id, status=JobStatus.RUNNING,
				status_message=stage, generation=spec.generation,
			))
		_service.prepare(model, token.check_cancelled, progress)
	elif operation == "cached":
		data["cached"] = _service.is_cached(model)
	elif operation == "delete":
		_service.delete(model)
	elif operation == "embed":
		texts = spec.payload.get("texts")
		if not isinstance(texts, list) or len(texts) > 256 or any(
			not isinstance(text, str) or len(text) > 4096 or not text.strip() for text in texts
		):
			raise ValueError("Invalid embedding batch")
		data["vectors"] = _service.embed(model, texts, token.check_cancelled) if texts else []
	else:
		raise ValueError("Unknown embedding operation")
	token.check_cancelled()
	return JobResult(job_id=spec.job_id, status=JobStatus.COMPLETED,
		result_data=data, generation=spec.generation)
