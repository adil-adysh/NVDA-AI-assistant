# -*- coding: utf-8 -*-
"""Application service for embedding model discovery and preparation."""
from __future__ import annotations

from dataclasses import dataclass
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


KNOWN_MODELS = (
	EmbeddingModelInfo("harrier-oss-v1-270m", "Harrier OSS 270M", 640, 32768, 536.0, "Gemma 3"),
	EmbeddingModelInfo("granite-embedding-97m-multilingual-r2", "Granite 97M", 384, 32768, 195.0, "ModernBERT"),
)


def embedding_cache_dir() -> Path:
	appdata = os.getenv("APPDATA")
	base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
	path = base / "nvda" / "AIAssistant" / "models" / "embeddings"
	path.mkdir(parents=True, exist_ok=True)
	return path


class EmbeddingModelService:
	"""Own model lifecycle without exposing native runtime details to UI."""

	def list_models(self) -> tuple[EmbeddingModelInfo, ...]:
		return KNOWN_MODELS

	def get_model(self, model_id: str) -> EmbeddingModelInfo:
		for model in KNOWN_MODELS:
			if model.id == model_id:
				return model
		raise ValueError(f"Unknown embedding model: {model_id}")

	def prepare(self, model_id: str, progress: Callable[[str], None] | None = None) -> None:
		model = self.get_model(model_id)
		if progress:
			progress(f"Preparing {model.name}…")
		try:
			import embedding_engine
		except ImportError as error:
			raise RuntimeError("The embedding engine is not installed") from error
		engine = embedding_engine.EmbeddingEngine(model.id, str(embedding_cache_dir()))
		# The native runtime downloads and validates all artifacts on first use.
		engine.embed("embedding model readiness check")
		if progress:
			progress(f"{model.name} is ready.")

	def is_cached(self, model_id: str) -> bool:
		try:
			import embedding_engine
			return bool(embedding_engine.EmbeddingEngine(model_id, str(embedding_cache_dir())).is_cached())
		except Exception:
			return False

	def delete(self, model_id: str) -> None:
		try:
			import embedding_engine
		except ImportError as error:
			raise RuntimeError("The embedding engine is not installed") from error
		embedding_engine.EmbeddingEngine.delete_cached(model_id, str(embedding_cache_dir()))


embedding_model_service = EmbeddingModelService()
