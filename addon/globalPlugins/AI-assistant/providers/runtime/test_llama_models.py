# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from .llama_models import (
	LlamaModelCatalog,
	LlamaModelRecord,
	build_models_preset,
	llama_model_capabilities,
	llama_model_context_window,
	merge_models_preset,
	parse_models_preset,
)
from .llama_server import build_llama_server_args
from ..model_import import ModelSourceKind


class LlamaModelsPresetTests(unittest.TestCase):
	def test_router_command_uses_preset_without_single_model_flag(self) -> None:
		args = build_llama_server_args(
			"model-a",
			host="127.0.0.1",
			port=9090,
			models_preset="C:/models/models.ini",
			context=8192,
		)

		self.assertEqual(
			args,
			[
				"--host",
				"127.0.0.1",
				"--port",
				"9090",
				"--models-preset",
				"C:/models/models.ini",
				"-c",
				"8192",
			],
		)
		self.assertNotIn("-m", args)
		self.assertNotIn("-hf", args)

	def test_local_and_hugging_face_records_are_exported(self) -> None:
		preset = build_models_preset(
			[
				LlamaModelRecord(
					model_id="local-model",
					source="model.gguf",
					kind=ModelSourceKind.LOCAL_FILE.value,
					local_path="C:/models/model.gguf",
				),
				LlamaModelRecord(
					model_id="org/model:Q4_K_M",
					source="org/model",
					kind=ModelSourceKind.HUGGING_FACE.value,
					variant="Q4_K_M",
				),
			]
		)

		self.assertTrue(preset.startswith("version = 1\n"))
		self.assertIn("[local-model]", preset)
		self.assertIn("model =", preset)
		self.assertIn("[org/model:Q4_K_M]", preset)
		self.assertIn("hf-repo = org/model:Q4_K_M", preset)
		self.assertNotIn("port", preset)
		self.assertNotIn("host", preset)

	def test_catalog_persists_records_and_writes_preset_atomically(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			catalog = LlamaModelCatalog(directory)
			record = LlamaModelRecord(
				model_id="model-a",
				source="model-a.gguf",
				kind=ModelSourceKind.LOCAL_FILE.value,
			)
			catalog.upsert(record)
			preset_path = catalog.write_preset()

			self.assertEqual(catalog.find("model-a"), record)
			self.assertEqual(preset_path, Path(directory) / "models.ini")
			self.assertIn("[model-a]", preset_path.read_text(encoding="utf-8"))

			catalog.remove("model-a")
			self.assertIsNone(catalog.find("model-a"))

	def test_existing_preset_options_are_preserved(self) -> None:
		original = """version = 1\n\n[*]\nctx-size = 36864\nflash-attn = true\n\n[gemma4-26b]\nhf-repo = old/repo:OLD\ntemperature = 0.6\n"""
		record = LlamaModelRecord(
			model_id="gemma4-26b",
			source="WhiskyAKM/Gemma-4-26B-A4B-NVFP4-GGUF",
			kind=ModelSourceKind.HUGGING_FACE.value,
			variant="NVFP4",
		)
		merged = merge_models_preset(original, [record])
		self.assertIn("ctx-size = 36864", merged)
		self.assertIn("temperature = 0.6", merged)
		self.assertIn("hf-repo = WhiskyAKM/Gemma-4-26B-A4B-NVFP4-GGUF:NVFP4", merged)
		self.assertEqual(parse_models_preset(merged)[0].model_id, "gemma4-26b")

	def test_catalog_resolves_hugging_face_source_to_preset_model_id(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			catalog = LlamaModelCatalog(directory)
			record = LlamaModelRecord(
				model_id="gemma4-26b",
				source="WhiskyAKM/Gemma-4-26B-A4B-NVFP4-GGUF",
				kind=ModelSourceKind.HUGGING_FACE.value,
				variant="NVFP4",
			)
			catalog.upsert(record)
			self.assertEqual(catalog.find("WhiskyAKM/Gemma-4-26B-A4B-NVFP4-GGUF:NVFP4"), record)
			self.assertEqual(catalog.find("hf://WhiskyAKM/Gemma-4-26B-A4B-NVFP4-GGUF:NVFP4"), record)

	def test_server_metadata_exposes_modalities_and_context(self) -> None:
		item = {
			"architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
			"meta": {"n_ctx_train": 131072},
		}
		self.assertIn("image_input", llama_model_capabilities(item))
		self.assertIn("text_output", llama_model_capabilities(item))
		self.assertEqual(llama_model_context_window(item), 131072)


if __name__ == "__main__":
	unittest.main()
