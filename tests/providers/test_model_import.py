from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tests.support import load_addon_module


model_import = load_addon_module("providers.model_import", namespace="provider_model_import_tests")
ModelSourceKind = model_import.ModelSourceKind
default_model_id_for_file = model_import.default_model_id_for_file
parse_model_import_source = model_import.parse_model_import_source


class ModelImportFileTests(unittest.TestCase):
	def test_default_model_id_uses_filename_stem(self) -> None:
		self.assertEqual(default_model_id_for_file(r"C:\models\Gemma-4.litertlm"), "Gemma-4")
		self.assertEqual(default_model_id_for_file(Path("Qwen3-8B.gguf")), "Qwen3-8B")

	def test_local_litert_file_is_validated(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "model.litertlm"
			path.write_bytes(b"model")
			request = parse_model_import_source(str(path), "model-id", "litert-lm")
			self.assertEqual(request.kind, ModelSourceKind.LOCAL_FILE)
			self.assertEqual(request.model_id, "model-id")

	def test_local_gguf_file_is_validated(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "model.gguf"
			path.write_bytes(b"model")
			request = parse_model_import_source(str(path), None, "llama-cpp-server")
			self.assertEqual(request.kind, ModelSourceKind.LOCAL_FILE)
			self.assertEqual(request.model_id, "model")

	def test_missing_or_wrong_extension_is_rejected(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			missing = Path(directory) / "missing.litertlm"
			with self.assertRaises(ValueError):
				parse_model_import_source(str(missing), None, "litert-lm")
			text_file = Path(directory) / "model.txt"
			text_file.write_text("not a model", encoding="utf-8")
			with self.assertRaises(ValueError):
				parse_model_import_source(str(text_file), None, "llama-cpp-server")

	def test_hugging_face_reference_remains_supported(self) -> None:
		request = parse_model_import_source(
			"org/model#file=model.litertlm",
			"runtime-id",
			"litert-lm",
		)
		self.assertEqual(request.kind, ModelSourceKind.HUGGING_FACE)
		self.assertEqual(request.artifact, "model.litertlm")


if __name__ == "__main__":
	unittest.main()
