from __future__ import annotations

from pathlib import Path
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
			@staticmethod
			def available_models() -> list[str]:
				return ["harrier-oss-v1-270m"]

			@staticmethod
			def model_info(model_id: str) -> dict[str, object]:
				return {"id": model_id, "name": "Harrier", "dimensions": 640, "max_tokens": 32768}

			def __init__(self, model_id: str, cache_dir: str) -> None:
				created.append((model_id, cache_dir))

		service = EmbeddingModelService()
		with patch("manager.embedding_cache_dir", return_value=Path("C:/embedding-cache")):
			engine = service._create_engine(types.SimpleNamespace(EmbeddingEngine=Engine), "model")

		self.assertIsInstance(engine, Engine)
		self.assertEqual(created, [("model", str(Path("C:/embedding-cache")))])

	def test_is_cached_delegates_to_native_engine(self) -> None:
		service = EmbeddingModelService()

		class Engine:
			@staticmethod
			def available_models() -> list[str]:
				return ["harrier-oss-v1-270m"]

			@staticmethod
			def model_info(model_id: str) -> dict[str, object]:
				return {"id": model_id, "name": "Harrier", "dimensions": 640, "max_tokens": 32768}

			def __init__(self, model_id: str, cache_dir: str) -> None:
				self.model_id = model_id
				self.cache_dir = cache_dir

			def is_cached(self) -> bool:
				return True

		with patch.object(service, "_load_native_engine", return_value=types.SimpleNamespace(EmbeddingEngine=Engine)):
			self.assertTrue(service.is_cached("harrier-oss-v1-270m"))

	def test_prepare_uses_native_prepare(self) -> None:
		service = EmbeddingModelService()
		prepared: list[bool] = []

		class Engine:
			@staticmethod
			def available_models() -> list[str]:
				return ["harrier-oss-v1-270m"]

			@staticmethod
			def model_info(model_id: str) -> dict[str, object]:
				return {"id": model_id, "name": "Harrier", "dimensions": 640, "max_tokens": 32768}

			def __init__(self, model_id: str, cache_dir: str) -> None:
				pass

			def prepare(self) -> None:
				prepared.append(True)

		with patch.object(service, "_load_native_engine", return_value=types.SimpleNamespace(EmbeddingEngine=Engine)):
			service.prepare("harrier-oss-v1-270m")
		self.assertEqual(prepared, [True])

	def test_delete_uses_native_cache_directory(self) -> None:
		service = EmbeddingModelService()
		deleted: list[tuple[str, str]] = []

		class Engine:
			@staticmethod
			def available_models() -> list[str]:
				return ["harrier-oss-v1-270m"]

			@staticmethod
			def model_info(model_id: str) -> dict[str, object]:
				return {"id": model_id, "name": "Harrier", "dimensions": 640, "max_tokens": 32768}

			@staticmethod
			def delete_cached(model_id: str, cache_dir: str) -> None:
				deleted.append((model_id, cache_dir))

		with patch.object(service, "_load_native_engine", return_value=types.SimpleNamespace(EmbeddingEngine=Engine)):
			with patch("manager.embedding_cache_dir", return_value=Path("C:/embedding-cache")):
				service.delete("harrier-oss-v1-270m")
		self.assertEqual(deleted, [("harrier-oss-v1-270m", str(Path("C:/embedding-cache")))])

if __name__ == "__main__":
	unittest.main()
