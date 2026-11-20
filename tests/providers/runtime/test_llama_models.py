# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path

from tests.support import load_addon_module

NAMESPACE = "llama_models_tests"
llama_models = load_addon_module("providers.runtime.llama_models", namespace=NAMESPACE)
llama_server = load_addon_module("providers.runtime.llama_server", namespace=NAMESPACE)
LlamaModelCatalog = llama_models.LlamaModelCatalog
LlamaModelRecord = llama_models.LlamaModelRecord
build_models_preset = llama_models.build_models_preset
llama_model_capabilities = llama_models.llama_model_capabilities
llama_model_context_window = llama_models.llama_model_context_window
build_llama_server_args = llama_server.build_llama_server_args


class LlamaModelsPresetTests(unittest.TestCase):
	def test_catalog_never_reads_an_external_preset(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			preset = Path(directory) / "custom.ini"
			preset.write_text("version = 1\n[local]\nhf-repo = owner/model\n", encoding="utf-8")
			catalog = LlamaModelCatalog(directory)
			self.assertEqual(catalog.list_records(), ())
			self.assertFalse((Path(directory) / "models.json").exists())

	def test_generated_preset_is_hf_only(self) -> None:
		record = LlamaModelRecord("selected", "org/model", file="model.gguf")
		preset = build_models_preset([record])
		self.assertIn("[selected]", preset)
		self.assertIn("hf-repo = org/model", preset)
		self.assertIn("hf-file = model.gguf", preset)
		self.assertNotIn("model =", preset)

	def test_generated_preset_edits_are_ignored_after_manifest_creation(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			catalog = LlamaModelCatalog(directory)
			catalog.upsert(LlamaModelRecord("selected", "org/old"))
			path = catalog.write_preset()
			path.write_text("version = 1\n[selected]\nhf-repo = org/new\nctx-size = 8192\n", encoding="utf-8")
			self.assertEqual(catalog.find("selected").repo, "org/old")
			self.assertIsNone(catalog.find("selected").context_window)

	def test_invalid_section_id_rejected_before_persistence(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			catalog = LlamaModelCatalog(directory)
			with self.assertRaises(ValueError):
				catalog.upsert(LlamaModelRecord("bad]", "org/model"))

	def test_router_command_uses_preset_without_single_model_flag(self) -> None:
		args = build_llama_server_args("model-a", host="127.0.0.1", port=9090,
			models_preset="C:/models/models.ini", context=8192)
		self.assertEqual(args, ["--host", "127.0.0.1", "--port", "9090",
			"--models-preset", "C:/models/models.ini", "-c", "8192"])
		self.assertNotIn("-m", args)
		self.assertNotIn("-hf", args)

	def test_record_identity_and_context(self) -> None:
		record = LlamaModelRecord("qwen", "owner/model", file="q.gguf", preset_options={"ctx-size": "4096"})
		self.assertTrue(record.matches_server_id("qwen"))
		self.assertTrue(record.matches_server_id("owner/model"))
		self.assertTrue(record.matches_server_id("q.gguf"))
		self.assertEqual(record.context_window, 4096)

	def test_server_metadata_exposes_modalities_and_context(self) -> None:
		item = {"architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
			"meta": {"n_ctx_train": 131072}}
		self.assertIn("image_input", llama_model_capabilities(item))
		self.assertEqual(llama_model_context_window(item), 131072)

	def test_speculative_mode_provenance_survives_catalog_updates(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			catalog = LlamaModelCatalog(directory)
			catalog.upsert(LlamaModelRecord("draft", "org/model", draft_repo="org/draft",
				draft_file="dflash.gguf", preset_options={"spec-type": "draft-dflash"},
				spec_type_auto=True))
			catalog.update_options("draft", {"spec-type": "draft-dflash", "ctx-size": "4096"})
			record = catalog.find_exact("draft")
			self.assertTrue(record.spec_type_auto)
			self.assertEqual(record.preset_options["ctx-size"], "4096")


if __name__ == "__main__":
	unittest.main()
