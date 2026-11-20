# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import unittest
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
		self.config = OpenAICompatConfig(
			provider="llama-cpp-server", model_name="qwen-preset",
			base_url="http://127.0.0.1:8080", timeout_seconds=30.0,
			enable_progress=False, num_ctx=0, max_retries=1, retry_backoff_seconds=0.1,
			generate_temperature=0.2, generate_top_k=0, generate_top_p=0.9, generate_max_tokens=512,
		)
		manager_module = load_addon_module("providers.llama_manager", namespace=NAMESPACE)
		with patch.object(llama_cpp, "LlamaCppModelManager", side_effect=lambda config: manager_module.LlamaCppModelManager(
			config, cache_dir=self.temp_dir.name, supervisor=MagicMock(models_error=None))):
			self.provider = LlamaCppServerProvider(self.config)
		self.provider._llama_manager._catalog.upsert(LlamaModelRecord(
			"qwen-preset", "unsloth/Qwen3-8B-GGUF", file="q.gguf",
			preset_options={"ctx-size": "8192", "reasoning": "on"}))
		self.provider._llama_manager._catalog.upsert(LlamaModelRecord(
			"vision-preset", "org/vision-model", file="v.gguf", preset_options={"ctx-size": "4096"}))

	def tearDown(self) -> None:
		self.temp_dir.cleanup()

	def test_preset_temperature_zero_overrides_global_request_default(self) -> None:
		self.provider._llama_manager._catalog.upsert(LlamaModelRecord(
			"qwen-preset", "owner/model", preset_options={"temperature": "0"}))
		with patch.object(llama_cpp.OpenAICompatProvider, "_resolve_sampling",
			return_value=llama_cpp.OpenAICompatProvider._resolve_sampling(self.provider, "qwen-preset")):
			with patch.object(llama_cpp, "get_model_sampling", return_value=llama_cpp.ModelSamplingConfig()):
				self.assertEqual(self.provider._resolve_sampling("qwen-preset").temperature, 0.0)

	def test_preset_prediction_limit_and_unlimited_requests(self) -> None:
		for limit, expected in (("512", 512), ("-1", None)):
			with self.subTest(limit=limit):
				self.provider._llama_manager._catalog.upsert(LlamaModelRecord(
					"qwen-preset", "owner/model", preset_options={"n-predict": limit}))
				with patch.object(llama_cpp, "get_model_sampling", return_value=llama_cpp.ModelSamplingConfig()):
					self.assertEqual(self.provider._resolve_sampling("qwen-preset").max_tokens, expected)

	def test_explicit_sampling_pins_win_over_preset_defaults(self) -> None:
		self.provider._llama_manager._catalog.upsert(LlamaModelRecord(
			"qwen-preset", "owner/model", preset_options={"temperature": "0", "n-predict": "512"}))
		pinned = llama_cpp.ModelSamplingConfig(temperature=0.7, max_tokens=256)
		with patch.object(llama_cpp.OpenAICompatProvider, "_resolve_sampling", return_value=pinned), \
			patch.object(llama_cpp, "get_model_sampling", return_value=pinned):
			self.assertEqual(self.provider._resolve_sampling("qwen-preset"), pinned)

	def test_list_models_offline_returns_catalog_records(self) -> None:
		with patch.object(self.provider._llama_manager, "list_server_models", return_value=()):
			models = self.provider.list_models()
			self.assertEqual({model.id for model in models}, {"qwen-preset", "vision-preset"})
			qwen = next(model for model in models if model.id == "qwen-preset")
			self.assertEqual(qwen.context_window, 8192)
			self.assertIn("thinking", qwen.capabilities)

	def test_list_models_online_ignores_server_only_entries(self) -> None:
		server_items = [{"id": "qwen-preset", "meta": {"n_ctx_train": 16384}},
			{"id": "dynamic-server-model", "owned_by": "llamacpp"}]
		with patch.object(self.provider._llama_manager, "list_server_models", return_value=server_items):
			model_ids = {model.id for model in self.provider.list_models()}
			self.assertEqual(model_ids, {"qwen-preset", "vision-preset"})

	def test_get_model_info_matches_exact_and_case_insensitive(self) -> None:
		with patch.object(self.provider._llama_manager, "list_server_models", return_value=()):
			self.assertEqual(self.provider.get_model_info("qwen-preset").id, "qwen-preset")
			self.assertEqual(self.provider.get_model_info("QWEN-PRESET").id, "qwen-preset")
			self.assertIsNone(self.provider.get_model_info("nonexistent"))
		empty_config = OpenAICompatConfig(
			provider="llama-cpp-server", model_name="", base_url="http://127.0.0.1:8080",
			timeout_seconds=30.0, enable_progress=False, num_ctx=0, max_retries=1,
			retry_backoff_seconds=0.1, generate_temperature=0.2, generate_top_k=0,
			generate_top_p=0.9, generate_max_tokens=512)
		self.assertIsNone(LlamaCppServerProvider(empty_config).get_model_info(None))

	def test_supports_image_description(self) -> None:
		with patch.object(self.provider, "get_model_info") as mock_info:
			mock_model = MagicMock()
			mock_model.supports.side_effect = lambda cap: cap == "image_input"
			mock_info.return_value = mock_model
			self.assertTrue(self.provider.supports_image_description())

	def test_ensure_model_available_requires_a_known_preset(self) -> None:
		with patch.object(self.provider._llama_manager, "ensure_running") as ensure:
			self.assertEqual(self.provider.ensure_model_available(), "qwen-preset")
			ensure.assert_called_once()
		bad_config = OpenAICompatConfig(
			provider="llama-cpp-server", model_name="completely-unknown",
			base_url="http://127.0.0.1:8080", timeout_seconds=30.0, enable_progress=False,
			num_ctx=0, max_retries=1, retry_backoff_seconds=0.1, generate_temperature=0.2,
			generate_top_k=0, generate_top_p=0.9, generate_max_tokens=512)
		with self.assertRaises(LLMProviderError):
			LlamaCppServerProvider(bad_config).ensure_model_available()

	def test_ensure_model_available_repairs_unique_repo_quant_selection(self) -> None:
		object.__setattr__(self.config, "model_name", "unsloth/Qwen3-8B-GGUF:NVFP4")
		with patch.object(self.provider._llama_manager, "ensure_running") as ensure:
			self.assertEqual(self.provider.ensure_model_available(), "qwen-preset")
			ensure.assert_called_once()
		self.assertEqual(self.config.model_name, "qwen-preset")

	def test_list_managed_models_exposes_presets_not_server_cache_ids(self) -> None:
		managed = self.provider._llama_manager.list_managed_models()
		self.assertEqual({model.id for model in managed}, {"qwen-preset", "vision-preset"})
		self.assertTrue(all(model.display_name for model in managed))


if __name__ == "__main__":
	unittest.main()
