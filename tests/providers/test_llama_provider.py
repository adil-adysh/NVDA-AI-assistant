# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.support import load_addon_module

NAMESPACE = "llama_provider_tests"
config_module = load_addon_module("providers.config", namespace=NAMESPACE)
llama_models = load_addon_module("providers.runtime.llama_models", namespace=NAMESPACE)
llama_cpp = load_addon_module("providers.adapters.llama_cpp", namespace=NAMESPACE)

OpenAICompatConfig = config_module.OpenAICompatConfig
LlamaModelRecord = llama_models.LlamaModelRecord
LlamaCppServerProvider = llama_cpp.LlamaCppServerProvider
LLMProviderError = llama_cpp.LLMProviderError


class LlamaCppServerProviderTests(unittest.TestCase):
	def setUp(self) -> None:
		self.temp_dir = tempfile.TemporaryDirectory()
		self.preset_file = Path(self.temp_dir.name) / "models.ini"
		self.preset_file.write_text(
			"version = 1\n\n"
			"[qwen-preset]\n"
			"hf-repo = unsloth/Qwen3-8B-GGUF:UD-Q4_K_XL\n"
			"ctx-size = 8192\n"
			"reasoning = on\n"
			"\n"
			"[vision-preset]\n"
			"hf-repo = org/vision-model:Q4_K_M\n"
			"ctx-size = 4096\n",
			encoding="utf-8",
		)
		self.config = OpenAICompatConfig(
			provider="llama-cpp-server",
			model_name="qwen-preset",
			base_url="http://127.0.0.1:8080",
			timeout_seconds=30.0,
			enable_progress=False,
			num_ctx=0,
			max_retries=1,
			retry_backoff_seconds=0.1,
			generate_temperature=0.2,
			generate_top_k=0,
			generate_top_p=0.9,
			generate_max_tokens=512,
			models_preset=str(self.preset_file),
		)
		self.provider = LlamaCppServerProvider(self.config)

	def tearDown(self) -> None:
		self.temp_dir.cleanup()

	def test_list_models_offline_returns_catalog_records(self) -> None:
		with patch.object(self.provider._llama_manager, "list_server_models", return_value=()):
			models = self.provider.list_models()
			model_ids = [m.id for m in models]
			self.assertIn("qwen-preset", model_ids)
			self.assertIn("vision-preset", model_ids)

			qwen = next(m for m in models if m.id == "qwen-preset")
			self.assertEqual(qwen.context_window, 8192)
			self.assertIn("thinking", qwen.capabilities)

	def test_list_models_online_merges_server_and_catalog(self) -> None:
		server_items = [
			{
				"id": "qwen-preset",
				"meta": {"n_ctx_train": 16384},
			},
			{
				"id": "dynamic-server-model",
				"owned_by": "llamacpp",
			},
		]
		with patch.object(self.provider._llama_manager, "list_server_models", return_value=server_items):
			models = self.provider.list_models()
			model_ids = [m.id for m in models]
			self.assertIn("qwen-preset", model_ids)
			self.assertIn("vision-preset", model_ids)
			self.assertIn("dynamic-server-model", model_ids)

			qwen = next(m for m in models if m.id == "qwen-preset")
			# Server metadata takes precedence for context window when online
			self.assertEqual(qwen.context_window, 16384)

	def test_get_model_info_matches_by_id_and_alias(self) -> None:
		with patch.object(self.provider._llama_manager, "list_server_models", return_value=()):
			# Exact match
			info = self.provider.get_model_info("qwen-preset")
			self.assertIsNotNone(info)
			self.assertEqual(info.id, "qwen-preset")

			# Case-insensitive match
			info_upper = self.provider.get_model_info("QWEN-PRESET")
			self.assertIsNotNone(info_upper)
			self.assertEqual(info_upper.id, "qwen-preset")

			# Match by Hugging Face reference
			info_hf = self.provider.get_model_info("unsloth/Qwen3-8B-GGUF:UD-Q4_K_XL")
			self.assertIsNotNone(info_hf)
			self.assertEqual(info_hf.id, "qwen-preset")

			# Unknown model returns None
			self.assertIsNone(self.provider.get_model_info("nonexistent-model"))

			# Default lookup (None or empty) resolves to configured model
			self.assertEqual(self.provider.get_model_info().id, "qwen-preset")
			self.assertEqual(self.provider.get_model_info("").id, "qwen-preset")

		# When no model is configured, empty lookup returns None
		empty_config = OpenAICompatConfig(
			provider="llama-cpp-server",
			model_name="",
			base_url="http://127.0.0.1:8080",
			timeout_seconds=30.0,
			enable_progress=False,
			num_ctx=0,
			max_retries=1,
			retry_backoff_seconds=0.1,
			generate_temperature=0.2,
			generate_top_k=0,
			generate_top_p=0.9,
			generate_max_tokens=512,
			models_preset=str(self.preset_file),
		)
		empty_provider = LlamaCppServerProvider(empty_config)
		self.assertIsNone(empty_provider.get_model_info(None))
		self.assertIsNone(empty_provider.get_model_info(""))

	def test_supports_image_description(self) -> None:
		with patch.object(self.provider, "get_model_info") as mock_info:
			mock_model = MagicMock()
			mock_model.supports.side_effect = lambda cap: cap == "image_input"
			mock_info.return_value = mock_model
			self.assertTrue(self.provider.supports_image_description())

			mock_model.supports.side_effect = lambda cap: False
			self.assertFalse(self.provider.supports_image_description())

	def test_ensure_model_available_validates_existence(self) -> None:
		with patch.object(self.provider._llama_manager, "ensure_running") as mock_ensure:
			# Valid model configured
			resolved = self.provider.ensure_model_available()
			self.assertEqual(resolved, "qwen-preset")
			mock_ensure.assert_called_once()

		# Unknown model raises LLMProviderError
		bad_config = OpenAICompatConfig(
			provider="llama-cpp-server",
			model_name="completely-unknown",
			base_url="http://127.0.0.1:8080",
			timeout_seconds=30.0,
			enable_progress=False,
			num_ctx=0,
			max_retries=1,
			retry_backoff_seconds=0.1,
			generate_temperature=0.2,
			generate_top_k=0,
			generate_top_p=0.9,
			generate_max_tokens=512,
			models_preset=str(self.preset_file),
		)
		bad_provider = LlamaCppServerProvider(bad_config)
		with self.assertRaises(LLMProviderError):
			bad_provider.ensure_model_available()


if __name__ == "__main__":
	unittest.main()
