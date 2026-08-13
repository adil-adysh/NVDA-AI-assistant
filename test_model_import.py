# -*- coding: utf-8 -*-
"""Tests for model import source parsing and safety rules."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


_PATH = Path(__file__).parent / "addon" / "globalPlugins" / "AI-assistant" / "providers" / "model_import.py"
_SPEC = importlib.util.spec_from_file_location("model_import", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)


class ModelImportTests(unittest.TestCase):
	def test_parses_hugging_face_repo_and_revision(self) -> None:
		request = _MODULE.parse_model_import_source("org/model:v1")
		self.assertEqual(request.kind, _MODULE.ModelSourceKind.HUGGING_FACE)
		self.assertEqual(request.source, "org/model")
		self.assertEqual(request.revision, "v1")
		self.assertEqual(request.model_id, "org-model-v1")

	def test_parses_local_litert_file_without_owning_source(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "custom.litertlm"
			path.write_bytes(b"model")
			request = _MODULE.parse_model_import_source(str(path), "custom-model")
		self.assertEqual(request.kind, _MODULE.ModelSourceKind.LOCAL_FILE)
		self.assertEqual(request.model_id, "custom-model")

	def test_parses_llama_quantization_as_variant(self) -> None:
		request = _MODULE.parse_model_import_source(
			"unsloth/Qwen3-8B-GGUF:UD-Q4_K_XL",
			provider_id="llama-cpp-server",
		)
		self.assertEqual(request.source, "unsloth/Qwen3-8B-GGUF")
		self.assertEqual(request.revision, "main")
		self.assertEqual(request.variant, "UD-Q4_K_XL")

	def test_parses_explicit_hugging_face_artifact(self) -> None:
		request = _MODULE.parse_model_import_source(
			"litert-community/gemma#file=gemma.litertlm",
			provider_id="litert-lm",
		)
		self.assertEqual(request.artifact, "gemma.litertlm")

	def test_rejects_unsupported_or_unsafe_sources(self) -> None:
		with self.assertRaises(_MODULE.ModelImportError):
			_MODULE.parse_model_import_source("org/model", "../unsafe")
		with self.assertRaises(_MODULE.ModelImportError):
			_MODULE.parse_model_import_source("C:/models/model.bin")


if __name__ == "__main__":
	unittest.main()
