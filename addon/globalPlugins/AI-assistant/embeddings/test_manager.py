from __future__ import annotations

from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

try:
	from .manager import EmbeddingModelService
except ImportError:
	from manager import EmbeddingModelService


class EmbeddingModelLifecycleTests(unittest.TestCase):
	def test_create_engine_supports_current_one_argument_api(self) -> None:
		created: list[str] = []

		class Engine:
			def __init__(self, model_id: str) -> None:
				created.append(model_id)

		service = EmbeddingModelService()
		engine = service._create_engine(types.SimpleNamespace(EmbeddingEngine=Engine), "model")

		self.assertIsInstance(engine, Engine)
		self.assertEqual(created, ["model"])

	def test_create_engine_supports_legacy_two_argument_api(self) -> None:
		created: list[tuple[str, str]] = []

		class Engine:
			def __init__(self, model_id: str, cache_dir: str) -> None:
				created.append((model_id, cache_dir))

		service = EmbeddingModelService()
		with patch("manager.embedding_cache_dir", return_value=Path("C:/embedding-cache")):
			engine = service._create_engine(types.SimpleNamespace(EmbeddingEngine=Engine), "model")

		self.assertIsInstance(engine, Engine)
		self.assertEqual(created, [("model", str(Path("C:/embedding-cache")))])

	def test_is_cached_requires_model_weight_artifacts(self) -> None:
		service = EmbeddingModelService()
		with tempfile.TemporaryDirectory() as directory:
			root = Path(directory)
			with patch.object(service, "_cache_roots", return_value=(root,)):
				self.assertFalse(service.is_cached("harrier-oss-v1-270m"))
				(root / "model.safetensors").write_bytes(b"weights" * 400)
				self.assertTrue(service.is_cached("harrier-oss-v1-270m"))

	def test_delete_removes_only_selected_model_roots(self) -> None:
		service = EmbeddingModelService()
		with tempfile.TemporaryDirectory() as directory:
			root = Path(directory) / "selected"
			other = Path(directory) / "other"
			root.mkdir()
			other.mkdir()
			with patch.object(service, "_cache_roots", return_value=(root,)):
				service.delete("harrier-oss-v1-270m")
			self.assertFalse(root.exists())
			self.assertTrue(other.exists())


if __name__ == "__main__":
	unittest.main()
