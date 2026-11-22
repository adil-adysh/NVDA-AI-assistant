from __future__ import annotations

from pathlib import Path
import types
import unittest
from unittest.mock import patch

from tests.support import load_addon_module


manager_module = load_addon_module("worker.executors.embedding", namespace="embedding_manager_tests")
EmbeddingModelService = manager_module.EmbeddingModelService


class EmbeddingModelLifecycleTests(unittest.TestCase):
	def test_create_engine_configures_bounded_offline_inference(self) -> None:
		created = []

		class Engine:
			def __init__(self, model_id, cache_dir, *, max_input_tokens, offline):
				created.append((model_id, cache_dir, max_input_tokens, offline))

		service = EmbeddingModelService()
		with patch.object(manager_module, "embedding_cache_dir", return_value=Path("C:/embedding-cache")):
			engine = service._create_engine(types.SimpleNamespace(EmbeddingEngine=Engine), "model")

		self.assertIsInstance(engine, Engine)
		self.assertEqual(created, [("model", str(Path("C:/embedding-cache")), 512, True)])

	def test_is_cached_delegates_to_native_engine(self) -> None:
		service = EmbeddingModelService()

		class Engine:
			@staticmethod
			def available_models() -> list[str]:
				return ["harrier-oss-v1-270m"]

			@staticmethod
			def model_info(model_id: str) -> dict[str, object]:
				return {"id": model_id, "name": "Harrier", "dimensions": 640, "max_tokens": 32768}

			def __init__(self, model_id: str, cache_dir: str, **options) -> None:
				self.model_id = model_id
				self.cache_dir = cache_dir

			def is_cached(self) -> bool:
				return True

		with patch.object(service, "_load_native_engine", return_value=types.SimpleNamespace(EmbeddingEngine=Engine)):
			self.assertTrue(service.is_cached("harrier-oss-v1-270m"))

	def test_prepare_downloads_validates_and_reuses_engine(self) -> None:
		service = EmbeddingModelService()
		prepared: list[str] = []

		class Engine:
			@staticmethod
			def available_models() -> list[str]:
				return ["harrier-oss-v1-270m"]

			@staticmethod
			def model_info(model_id: str) -> dict[str, object]:
				return {"id": model_id, "name": "Harrier", "dimensions": 640, "max_tokens": 32768}

			def __init__(self, model_id: str, cache_dir: str, **options) -> None:
				pass

			def download(self, check_cancelled) -> None:
				check_cancelled()
				prepared.append("download")

			def validate(self) -> None:
				prepared.append("validate")

		with patch.object(service, "_load_native_engine", return_value=types.SimpleNamespace(EmbeddingEngine=Engine)):
			service.prepare("harrier-oss-v1-270m")
			self.assertIs(service._engine, service.engine_for("harrier-oss-v1-270m"))
		self.assertEqual(prepared, ["download", "validate"])

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
			with patch.object(manager_module, "embedding_cache_dir", return_value=Path("C:/embedding-cache")):
				service.delete("harrier-oss-v1-270m")
		self.assertEqual(deleted, [("harrier-oss-v1-270m", str(Path("C:/embedding-cache")))])

	def test_prepare_checks_cancellation_before_model_validation(self) -> None:
		service = EmbeddingModelService()
		validated = False

		class Cancelled(Exception):
			pass

		def check_cancelled() -> None:
			raise Cancelled()

		class Engine:
			def download(self, callback) -> None:
				self.callback = callback

			def validate(self) -> None:
				nonlocal validated
				validated = True

		engine = Engine()
		with patch.object(service, "engine_for", return_value=engine):
			with self.assertRaises(Cancelled):
				service.prepare("model", check_cancelled)
		self.assertIs(engine.callback, check_cancelled)
		self.assertFalse(validated)

	def test_missing_cached_model_does_not_start_inference(self) -> None:
		service = EmbeddingModelService()
		engine = types.SimpleNamespace(is_cached=lambda: False)
		with patch.object(service, "engine_for", return_value=engine):
			with self.assertRaisesRegex(RuntimeError, "needs to be downloaded"):
				service.embed("model", ["passage"], lambda: None)

if __name__ == "__main__":
	unittest.main()
