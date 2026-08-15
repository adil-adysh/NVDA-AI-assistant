# -*- coding: utf-8 -*-
"""Application service for embedding model discovery and preparation."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
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
	EmbeddingModelInfo("harrier-oss-v1-270m", "Harrier OSS 270M", 640, 32768, 545.0, "Gemma 3"),
	EmbeddingModelInfo("granite-embedding-97m-multilingual-r2", "Granite 97M", 384, 32768, 186.0, "ModernBERT"),
)

_MODEL_REPOSITORIES = {
	"harrier-oss-v1-270m": "models--microsoft--harrier-oss-v1-270m",
	"granite-embedding-97m-multilingual-r2": "models--ibm-granite--granite-embedding-97m-multilingual-r2",
}


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
		engine = self._create_engine(embedding_engine, model.id)
		# The native runtime downloads and validates all artifacts on first use.
		engine.embed("embedding model readiness check")
		if progress:
			progress(f"{model.name} is ready.")

	def is_cached(self, model_id: str) -> bool:
		try:
			self.get_model(model_id)
			return any(self._has_artifacts(root) for root in self._cache_roots(model_id))
		except Exception:
			return False

	def delete(self, model_id: str) -> None:
		self.get_model(model_id)
		for root in self._cache_roots(model_id):
			if root.exists():
				shutil.rmtree(root)

	def _create_engine(self, embedding_engine: Any, model_id: str) -> Any:
		"""Construct old and new native engine APIs."""
		try:
			return embedding_engine.EmbeddingEngine(model_id, str(embedding_cache_dir()))
		except TypeError:
			# Current versions manage their own Hugging Face cache and accept only
			# the model ID.
			return embedding_engine.EmbeddingEngine(model_id)

	def _cache_roots(self, model_id: str) -> tuple[Path, ...]:
		repository = _MODEL_REPOSITORIES.get(model_id)
		if repository is None:
			return ()
		user_cache = Path.home() / ".cache" / "huggingface" / "hub"
		return (
			embedding_cache_dir() / repository,
			user_cache / repository,
		)

	@staticmethod
	def _has_artifacts(root: Path) -> bool:
		if not root.is_dir():
			return False
		return any(
			path.is_file() and path.stat().st_size > 1024
			for path in root.rglob("*")
			if path.name.endswith((".safetensors", ".bin", ".gguf"))
		)


embedding_model_service = EmbeddingModelService()
