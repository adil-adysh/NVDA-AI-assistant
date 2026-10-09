# -*- coding: utf-8 -*-
"""Empirical Challenge Suite 2 for Migration Slice 8.

Validates:
1. Invariant A14 (Zero Silent Fallbacks, F-F03) in ensure_provider_server_ready().
2. Invariant A7 & RS-10 (Zero Production Test Shims in server.py and llama_server.py).
3. LiteRT candidate ordering and edge case resilience in providers.litert_models.
"""
from __future__ import annotations

import ast
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tests.support import ADDON_ROOT, load_addon_module, load_module, register_package

# Setup test package namespace for plugin.background isolation
NAMESPACE = "slice8_challenge_c2_testpkg"
register_package(NAMESPACE, ADDON_ROOT)
register_package(f"{NAMESPACE}.plugin", ADDON_ROOT / "plugin")
for package_name in ("config", "providers", "providers.runtime", "service", "ui", "use_case"):
	register_package(f"{NAMESPACE}.{package_name}", ADDON_ROOT.joinpath(*package_name.split(".")))


def _stub(relative_name: str, **attributes: object) -> types.ModuleType:
	module = types.ModuleType(f"{NAMESPACE}.{relative_name}")
	for name, value in attributes.items():
		setattr(module, name, value)
	sys.modules[module.__name__] = module
	return module


class _LLMProviderError(RuntimeError):
	pass


class _ProviderConfigurationError(RuntimeError):
	pass


class _LiteRTServerError(RuntimeError):
	pass


_stub(
	"providers.interfaces",
	LLMProviderError=_LLMProviderError,
	ProviderConfigurationError=_ProviderConfigurationError,
)
_stub(
	"providers.runtime.server",
	LiteRTServerError=_LiteRTServerError,
	get_litert_supervisor=lambda: SimpleNamespace(),
)
_stub("providers.runtime.llama_server", shutdown_llama_servers=lambda: None)
_stub("providers.llama_manager", LlamaCppModelManager=MagicMock)
_stub(
	"service.error_reporter",
	ErrorContext=lambda **kwargs: kwargs,
	error_reporter=SimpleNamespace(report=lambda *_args, **_kwargs: None),
)
_stub("service.llm", LLMService=object)
_stub(
	"service.model_cache",
	model_catalog_cache=SimpleNamespace(refresh_async=lambda _p: None),
)
_stub(
	"service.provider_readiness",
	ProviderReadinessService=lambda: SimpleNamespace(),
	get_provider_display_name=str,
)
_stub(
	"config.settings",
	get_provider=lambda: "none",
	get_model_name=lambda: "",
	get_active_provider_config=lambda: SimpleNamespace(provider="none", model_name=""),
	set_model_name=lambda _name: None,
)
_stub(
	"config.state",
	subscribe_litert_server_config_change=lambda _callback: None,
	subscribe_llama_server_config_change=lambda _callback: None,
)
_stub("ui.nvda_ui", queue=lambda *_args: None, message=lambda *_args: None)
_stub("ui.session_state", build_provider_status_message=lambda *_args: "")
_stub("use_case.engine", UseCaseEngine=object)
_stub(
	"use_case.types",
	UseCaseId=str,
	ATTACH_FOCUSED_IMAGE_TO_CHAT="attach-focused",
	OPEN_CHAT="open-chat",
	OPEN_CHAT_WITH_PAGE_CONTENT="open-page-chat",
	OPEN_CHAT_WITH_SCREENSHOT="open-screenshot-chat",
)

background = load_module(
	f"{NAMESPACE}.plugin.background",
	ADDON_ROOT / "plugin" / "background.py",
)
litert_models = load_addon_module("providers.litert_models")
runtime_server = load_addon_module("providers.runtime.server")
runtime_llama_server = load_addon_module("providers.runtime.llama_server")


class InvariantA14AdversarialProbingTests(unittest.TestCase):
	"""Empirically test Invariant A14 fail-closed model verification."""

	def setUp(self) -> None:
		self.settings_mod = sys.modules[f"{NAMESPACE}.config.settings"]
		self.model_cache_mod = sys.modules[f"{NAMESPACE}.service.model_cache"]
		self.set_model_calls: list[str] = []
		self.refreshed_providers: list[str] = []
		self.mock_cache = SimpleNamespace(refresh_async=self.refreshed_providers.append)

	def _run_with_model_name(
		self,
		model_name: object,
		catalog_presets: list[SimpleNamespace] | None = None,
	) -> tuple[MagicMock, Exception | None]:
		config = SimpleNamespace(
			provider="llama-cpp-server",
			model_name=model_name,
		)
		mock_manager = MagicMock()
		mock_manager.find_record.return_value = None
		mock_manager._catalog.list_records.return_value = catalog_presets or [
			SimpleNamespace(model_id="preset-qwen-7b"),
			SimpleNamespace(model_id="preset-llama-3b"),
		]

		raised_exc: Exception | None = None
		with patch.object(background, "get_provider", return_value="llama-cpp-server"), \
			 patch.object(self.settings_mod, "get_active_provider_config", return_value=config), \
			 patch.object(self.settings_mod, "set_model_name", side_effect=self.set_model_calls.append), \
			 patch.object(background, "LlamaCppModelManager", return_value=mock_manager), \
			 patch.object(self.model_cache_mod, "model_catalog_cache", self.mock_cache):
			try:
				background.ensure_provider_server_ready()
			except Exception as exc:  # noqa: BLE001
				raised_exc = exc

		return mock_manager, raised_exc

	def test_unknown_model_strictly_fails_closed_without_preset_fallback(self) -> None:
		"""Ensure unknown model raises LLMProviderError without fallback to available presets."""
		mock_manager, exc = self._run_with_model_name("completely-unknown-model-xyz")

		self.assertIsInstance(exc, background.LLMProviderError)
		self.assertEqual(str(exc), "Unknown llama.cpp model: completely-unknown-model-xyz")
		mock_manager.ensure_running.assert_not_called()
		self.assertEqual(self.set_model_calls, [])
		self.assertEqual(self.refreshed_providers, [])

	def test_empty_string_model_fails_closed(self) -> None:
		"""Ensure empty string model raises LLMProviderError and does not launch server."""
		mock_manager, exc = self._run_with_model_name("")

		self.assertIsInstance(exc, background.LLMProviderError)
		self.assertEqual(str(exc), "Unknown llama.cpp model: ")
		mock_manager.ensure_running.assert_not_called()
		self.assertEqual(self.set_model_calls, [])
		self.assertEqual(self.refreshed_providers, [])

	def test_whitespace_string_model_fails_closed(self) -> None:
		"""Ensure whitespace-only model raises LLMProviderError with raw value."""
		whitespace_value = "   \t \r\n  "
		mock_manager, exc = self._run_with_model_name(whitespace_value)

		self.assertIsInstance(exc, background.LLMProviderError)
		self.assertEqual(str(exc), f"Unknown llama.cpp model: {whitespace_value}")
		mock_manager.ensure_running.assert_not_called()
		self.assertEqual(self.set_model_calls, [])
		self.assertEqual(self.refreshed_providers, [])

	def test_none_model_fails_closed(self) -> None:
		"""Ensure None model raises LLMProviderError and never mutates config."""
		mock_manager, exc = self._run_with_model_name(None)

		self.assertIsInstance(exc, background.LLMProviderError)
		self.assertEqual(str(exc), "Unknown llama.cpp model: None")
		mock_manager.ensure_running.assert_not_called()
		self.assertEqual(self.set_model_calls, [])
		self.assertEqual(self.refreshed_providers, [])

	def test_non_string_model_types_fail_closed(self) -> None:
		"""Ensure numeric and boolean model_name types fail closed without crashes."""
		for non_str_val in (12345, False, True):
			with self.subTest(val=non_str_val):
				mock_manager, exc = self._run_with_model_name(non_str_val)
				self.assertIsInstance(exc, background.LLMProviderError)
				self.assertEqual(str(exc), f"Unknown llama.cpp model: {non_str_val}")
				mock_manager.ensure_running.assert_not_called()
				self.assertEqual(self.set_model_calls, [])

	def test_known_model_starts_normally(self) -> None:
		"""Ensure valid model proceeds to ensure_running and refreshes catalog cache."""
		config = SimpleNamespace(
			provider="llama-cpp-server",
			model_name="valid-model-gguf",
		)
		valid_record = SimpleNamespace(model_id="valid-model-gguf")
		mock_manager = MagicMock()
		mock_manager.find_record.return_value = valid_record

		with patch.object(background, "get_provider", return_value="llama-cpp-server"), \
			 patch.object(self.settings_mod, "get_active_provider_config", return_value=config), \
			 patch.object(self.settings_mod, "set_model_name", side_effect=self.set_model_calls.append), \
			 patch.object(background, "LlamaCppModelManager", return_value=mock_manager), \
			 patch.object(self.model_cache_mod, "model_catalog_cache", self.mock_cache):
			background.ensure_provider_server_ready()

		mock_manager.ensure_running.assert_called_once_with(valid_record, on_progress=None)
		self.assertEqual(self.set_model_calls, [])
		self.assertEqual(self.refreshed_providers, ["llama-cpp-server"])

	def test_other_providers_exit_immediately(self) -> None:
		"""Ensure non-managed providers exit cleanly without checking llama models."""
		for non_managed in ("openai", "anthropic", "ollama", "custom-api"):
			with self.subTest(provider=non_managed):
				with patch.object(background, "get_provider", return_value=non_managed), \
					 patch.object(background, "LlamaCppModelManager") as mock_mgr_cls:
					background.ensure_provider_server_ready()
					mock_mgr_cls.assert_not_called()


class ProductionTestShimEliminationTests(unittest.TestCase):
	"""Empirically test Invariant A7 & RS-10 (Zero Production Test Shims)."""

	def test_server_module_does_not_export_test_shim_supervisor(self) -> None:
		"""Verify _TestShimSupervisor symbol cannot be imported or accessed from server.py."""
		self.assertFalse(
			hasattr(runtime_server, "_TestShimSupervisor"),
			"_TestShimSupervisor must NOT exist on providers.runtime.server",
		)
		self.assertNotIn("_TestShimSupervisor", dir(runtime_server))
		with self.assertRaises(AttributeError):
			getattr(runtime_server, "_TestShimSupervisor")

	def test_llama_server_module_does_not_export_llama_test_shim_supervisor(self) -> None:
		"""Verify _LlamaTestShimSupervisor symbol cannot be imported or accessed from llama_server.py."""
		self.assertFalse(
			hasattr(runtime_llama_server, "_LlamaTestShimSupervisor"),
			"_LlamaTestShimSupervisor must NOT exist on providers.runtime.llama_server",
		)
		self.assertNotIn("_LlamaTestShimSupervisor", dir(runtime_llama_server))
		with self.assertRaises(AttributeError):
			getattr(runtime_llama_server, "_LlamaTestShimSupervisor")

	def test_litert_supervisor_get_native_returns_none_without_native_supervisor(self) -> None:
		"""Verify LiteRTServerSupervisor._get_native() returns None and does not build a test shim."""
		supervisor = runtime_server.LiteRTServerSupervisor()
		self.assertIsNone(supervisor._get_native())

	def test_llama_supervisor_get_native_returns_none_with_process_factory(self) -> None:
		"""Verify LlamaServerSupervisor._get_native() returns None even with process_factory set."""
		supervisor = runtime_llama_server.LlamaServerSupervisor(process_factory=MagicMock())
		self.assertIsNone(supervisor._get_native())

	def test_background_module_does_not_contain_obsolete_symbols_or_threads(self) -> None:
		"""Verify background.py has no obsolete aliases or thread worker functions."""
		obsolete_names = (
			"_ensure_litert_server_ready_locked",
			"_on_litert_server_config_changed",
			"_restart_litert_server_worker",
			"_on_llama_server_config_changed",
		)
		for name in obsolete_names:
			with self.subTest(symbol=name):
				self.assertFalse(
					hasattr(background, name),
					f"Obsolete symbol {name} must NOT exist in plugin.background",
				)

	def test_ast_audit_verifies_zero_test_shims_in_runtime_source_files(self) -> None:
		"""Static AST check: production source files must not define shadow test shim classes."""
		server_py = ADDON_ROOT / "providers" / "runtime" / "server.py"
		llama_py = ADDON_ROOT / "providers" / "runtime" / "llama_server.py"

		tree_server = ast.parse(server_py.read_text(encoding="utf-8"))
		class_names_server = [
			node.name for node in ast.walk(tree_server) if isinstance(node, ast.ClassDef)
		]
		self.assertNotIn("_TestShimSupervisor", class_names_server)

		tree_llama = ast.parse(llama_py.read_text(encoding="utf-8"))
		class_names_llama = [
			node.name for node in ast.walk(tree_llama) if isinstance(node, ast.ClassDef)
		]
		self.assertNotIn("_LlamaTestShimSupervisor", class_names_llama)

	def test_ast_audit_verifies_no_background_config_subscriptions(self) -> None:
		"""Static AST check: background.py must not subscribe to config changes."""
		bg_py = ADDON_ROOT / "plugin" / "background.py"
		code = bg_py.read_text(encoding="utf-8")
		self.assertNotIn("subscribe_litert_server_config_change", code)
		self.assertNotIn("subscribe_llama_server_config_change", code)
		self.assertNotIn("litert-restart-on-config-change", code)
		self.assertNotIn("llama-shutdown-on-config-change", code)


class LiteRTCandidateOrderingTests(unittest.TestCase):
	"""Empirically test build_import_candidates variant ordering and edge cases."""

	def setUp(self) -> None:
		self.v_cpu1 = SimpleNamespace(filename="model-cpu-q4.litertlm", platform_hint="cpu")
		self.v_cpu2 = SimpleNamespace(filename="model-cpu-q8.litertlm", platform_hint="cpu")
		self.v_gpu1 = SimpleNamespace(filename="model-gpu-fp16.litertlm", platform_hint="gpu")
		self.v_gpu2 = SimpleNamespace(filename="model-gpu-int4.litertlm", platform_hint="gpu")

	def test_gpu_system_orders_gpu_before_cpu_and_appends_primary(self) -> None:
		"""When has_gpu() is True, GPU variants come before CPU variants, primary last."""
		model_def = SimpleNamespace(
			has_variants=True,
			filename="primary-fallback.litertlm",
			variants=(self.v_cpu1, self.v_gpu1, self.v_cpu2, self.v_gpu2),
		)
		with patch.object(litert_models, "has_gpu", return_value=True):
			candidates = litert_models.build_import_candidates(model_def)

		expected = [
			"model-gpu-fp16.litertlm",
			"model-gpu-int4.litertlm",
			"model-cpu-q4.litertlm",
			"model-cpu-q8.litertlm",
			"primary-fallback.litertlm",
		]
		self.assertEqual(candidates, expected)

	def test_cpu_system_orders_cpu_before_gpu_and_appends_primary(self) -> None:
		"""When has_gpu() is False, CPU variants come before GPU variants, primary last."""
		model_def = SimpleNamespace(
			has_variants=True,
			filename="primary-fallback.litertlm",
			variants=(self.v_gpu1, self.v_cpu1, self.v_gpu2, self.v_cpu2),
		)
		with patch.object(litert_models, "has_gpu", return_value=False):
			candidates = litert_models.build_import_candidates(model_def)

		expected = [
			"model-cpu-q4.litertlm",
			"model-cpu-q8.litertlm",
			"model-gpu-fp16.litertlm",
			"model-gpu-int4.litertlm",
			"primary-fallback.litertlm",
		]
		self.assertEqual(candidates, expected)

	def test_primary_already_in_variants_is_not_duplicated(self) -> None:
		"""If primary filename is one of the variant files, it must not be appended twice."""
		v_primary_cpu = SimpleNamespace(filename="shared-primary.litertlm", platform_hint="cpu")
		model_def = SimpleNamespace(
			has_variants=True,
			filename="shared-primary.litertlm",
			variants=(self.v_gpu1, v_primary_cpu),
		)
		with patch.object(litert_models, "has_gpu", return_value=True):
			candidates = litert_models.build_import_candidates(model_def)

		self.assertEqual(
			candidates,
			["model-gpu-fp16.litertlm", "shared-primary.litertlm"],
		)
		self.assertEqual(candidates.count("shared-primary.litertlm"), 1)

	def test_empty_and_none_definitions(self) -> None:
		"""Test boundary conditions for empty/None definitions."""
		self.assertEqual(litert_models.build_import_candidates(None), [])
		self.assertEqual(litert_models.build_import_candidates(SimpleNamespace()), [])
		self.assertEqual(
			litert_models.build_import_candidates(SimpleNamespace(filename="test.bin")),
			["test.bin"],
		)
		self.assertEqual(
			litert_models.build_import_candidates(SimpleNamespace(has_variants=True, filename="", variants=())),
			[],
		)

	def test_variant_with_empty_or_none_filename_omitted(self) -> None:
		"""Variants with empty, None, or missing filenames are skipped."""
		v_empty = SimpleNamespace(filename="", platform_hint="gpu")
		v_none = SimpleNamespace(filename=None, platform_hint="gpu")
		v_valid = SimpleNamespace(filename="valid.litertlm", platform_hint="cpu")
		model_def = SimpleNamespace(
			has_variants=True,
			filename="primary.litertlm",
			variants=(v_empty, v_none, v_valid),
		)
		with patch.object(litert_models, "has_gpu", return_value=True):
			candidates = litert_models.build_import_candidates(model_def)

		self.assertEqual(candidates, ["valid.litertlm", "primary.litertlm"])

	def test_non_standard_platform_hints_routed_to_cpu(self) -> None:
		"""Variants with unknown or non-standard platform_hint are treated safely as CPU."""
		v_npu = SimpleNamespace(filename="model-npu.litertlm", platform_hint="npu")
		v_custom = SimpleNamespace(filename="model-custom.litertlm", platform_hint="dsp")
		model_def = SimpleNamespace(
			has_variants=True,
			filename="",
			variants=(self.v_gpu1, v_npu, v_custom),
		)
		with patch.object(litert_models, "has_gpu", return_value=True):
			candidates = litert_models.build_import_candidates(model_def)

		self.assertEqual(candidates[0], "model-gpu-fp16.litertlm")
		self.assertIn("model-npu.litertlm", candidates[1:])
		self.assertIn("model-custom.litertlm", candidates[1:])

	def test_all_catalog_definitions_produce_valid_unique_candidates(self) -> None:
		"""Stress test: every built-in catalog model definition produces valid candidate lists."""
		models = litert_models.ALL_MODELS
		self.assertGreater(len(models), 0, "Catalog must contain at least one model definition")

		for model in models:
			for has_gpu_mode in (True, False):
				with patch.object(litert_models, "has_gpu", return_value=has_gpu_mode):
					candidates = litert_models.build_import_candidates(model)
				self.assertIsInstance(candidates, list)
				self.assertGreater(len(candidates), 0)
				# All candidates must be non-empty strings
				for c in candidates:
					self.assertIsInstance(c, str)
					self.assertTrue(len(c.strip()) > 0)
				# Verify candidate list has no duplicates
				self.assertEqual(len(candidates), len(set(candidates)))

	def test_backward_compatibility_alias_preserved(self) -> None:
		"""Verify _build_import_candidates is exported and identical to build_import_candidates."""
		self.assertTrue(hasattr(litert_models, "_build_import_candidates"))
		self.assertIs(
			litert_models._build_import_candidates,
			litert_models.build_import_candidates,
		)


if __name__ == "__main__":
	unittest.main()
