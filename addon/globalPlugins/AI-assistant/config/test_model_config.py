# -*- coding: utf-8 -*-
# Pylint cannot infer attributes assigned to types.ModuleType() fakes used
# to stub NVDA-internal modules (E1101 ``__name__`` false positives).
# Test files deliberately duplicate the self-contained synthetic-package
# bootstrap so each suite can run standalone (R0801).
# pylint: disable=no-member,duplicate-code
from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent
ROOT_DIR = MODULE_DIR.parent
PACKAGE_NAME = "model_config_testpkg"


def _register_package(name: str, path: Path | None = None) -> types.ModuleType:
	module = types.ModuleType(name)
	if path is not None:
		module.__path__ = [str(path)]
	sys.modules[name] = module
	return module


def _load_module(module_name: str, file_path: Path):
	spec = importlib.util.spec_from_file_location(module_name, file_path)
	if spec is None or spec.loader is None:
		raise RuntimeError(f"Unable to load {module_name}")
	module = importlib.util.module_from_spec(spec)
	sys.modules[module_name] = module
	spec.loader.exec_module(module)
	return module


_register_package(PACKAGE_NAME, ROOT_DIR)
_register_package(f"{PACKAGE_NAME}.config", ROOT_DIR / "config")

model_config_module = _load_module(
	f"{PACKAGE_NAME}.config.model_config",
	ROOT_DIR / "config" / "model_config.py",
)

ModelSamplingConfig = model_config_module.ModelSamplingConfig
MODEL_CONFIG_FIELDS = model_config_module.MODEL_CONFIG_FIELDS
SAMPLING_FIELD_IDS = model_config_module.SAMPLING_FIELD_IDS


def _with_temp_store(test_case: unittest.TestCase) -> None:
	"""Point the store at a temp file so tests never touch real APPDATA."""
	tmp_dir = tempfile.mkdtemp()
	test_case.addCleanup(shutil.rmtree, tmp_dir, ignore_errors=True)
	model_config_module._store_path = lambda: Path(tmp_dir) / "model_configs.json"  # pylint: disable=protected-access


class ModelConfigStoreTests(unittest.TestCase):
	"""Persistence: set / get / clear round-trips, per-provider isolation."""

	def setUp(self) -> None:
		_with_temp_store(self)

	def test_round_trip_get_set_clear(self) -> None:
		store = model_config_module.ModelConfigStore()
		store.set("openai", "gpt-4o", {"temperature": 0.7, "top_k": 40})
		self.assertEqual(
			store.get("openai", "gpt-4o"),
			{"temperature": 0.7, "top_k": 40},
		)
		store.clear("openai", "gpt-4o")
		self.assertEqual(store.get("openai", "gpt-4o"), {})

	def test_missing_model_returns_empty(self) -> None:
		store = model_config_module.ModelConfigStore()
		self.assertEqual(store.get("ollama", "llama3.2"), {})

	def test_providers_are_isolated(self) -> None:
		store = model_config_module.ModelConfigStore()
		store.set("openai", "gemma-4-E2B", {"num_ctx": 4096})
		store.set("litert-lm", "gemma-4-E2B", {"num_ctx": 32768})
		self.assertEqual(store.get("openai", "gemma-4-E2B"), {"num_ctx": 4096})
		self.assertEqual(store.get("litert-lm", "gemma-4-E2B"), {"num_ctx": 32768})

	def test_clear_keeps_other_models(self) -> None:
		store = model_config_module.ModelConfigStore()
		store.set("ollama", "a", {"temperature": 0.5})
		store.set("ollama", "b", {"temperature": 0.9})
		store.clear("ollama", "a")
		self.assertEqual(store.get("ollama", "a"), {})
		self.assertEqual(store.get("ollama", "b"), {"temperature": 0.9})


class ModelSamplingHelpersTests(unittest.TestCase):
	"""API helpers: get / set / clear / resolve semantics."""

	def setUp(self) -> None:
		_with_temp_store(self)

	def test_set_skips_none_fields(self) -> None:
		model_config_module.set_model_sampling(
			"openai",
			"gpt-4o",
			ModelSamplingConfig(temperature=0.7),
		)
		raw = model_config_module.ModelConfigStore().get("openai", "gpt-4o")
		self.assertEqual(raw, {"temperature": 0.7})

	def test_get_returns_explicit_only(self) -> None:
		model_config_module.set_model_sampling(
			"ollama",
			"llama3.2",
			ModelSamplingConfig(num_ctx=4096, top_k=20),
		)
		cfg = model_config_module.get_model_sampling("ollama", "llama3.2")
		self.assertEqual(cfg.num_ctx, 4096)
		self.assertEqual(cfg.top_k, 20)
		self.assertIsNone(cfg.temperature)
		self.assertIsNone(cfg.repeat_penalty)

	def test_resolve_explicit_overrides_base(self) -> None:
		base = ModelSamplingConfig(num_ctx=8192, temperature=0.2, top_p=0.85, max_tokens=1024)
		model_config_module.set_model_sampling(
			"openai",
			"gpt-4o",
			ModelSamplingConfig(temperature=0.9, max_tokens=2048),
		)
		resolved = model_config_module.resolve_model_sampling("openai", "gpt-4o", base)
		self.assertEqual(resolved.temperature, 0.9)
		self.assertEqual(resolved.max_tokens, 2048)
		self.assertEqual(resolved.num_ctx, 8192)
		self.assertEqual(resolved.top_p, 0.85)

	def test_resolve_unpinned_returns_base(self) -> None:
		base = ModelSamplingConfig(num_ctx=4096, temperature=0.1, top_p=0.9, max_tokens=512)
		resolved = model_config_module.resolve_model_sampling("ollama", "llama3.2", base)
		self.assertEqual(resolved, base)

	def test_resolve_pinned_only_fields_none_without_explicit(self) -> None:
		# top_k / repeat_penalty must never leak from a global base.
		base = ModelSamplingConfig(num_ctx=8192, temperature=0.2, top_p=0.85, max_tokens=1024)
		resolved = model_config_module.resolve_model_sampling("openai", "gpt-4o", base)
		self.assertIsNone(resolved.top_k)
		self.assertIsNone(resolved.repeat_penalty)

	def test_resolve_pinned_only_fields_used_when_pinned(self) -> None:
		base = ModelSamplingConfig(num_ctx=8192, temperature=0.2, top_p=0.85, max_tokens=1024)
		model_config_module.set_model_sampling(
			"litert-lm",
			"gemma-4-E2B",
			ModelSamplingConfig(top_k=40, repeat_penalty=1.1),
		)
		resolved = model_config_module.resolve_model_sampling("litert-lm", "gemma-4-E2B", base)
		self.assertEqual(resolved.top_k, 40)
		self.assertEqual(resolved.repeat_penalty, 1.1)
		# Wire-fallback fields still come from the base.
		self.assertEqual(resolved.num_ctx, 8192)

	def test_clear_model_sampling_removes_entry(self) -> None:
		base = ModelSamplingConfig(num_ctx=8192, temperature=0.2, top_p=0.85, max_tokens=1024)
		model_config_module.set_model_sampling(
			"openai",
			"gpt-4o",
			ModelSamplingConfig(temperature=0.9),
		)
		model_config_module.clear_model_sampling("openai", "gpt-4o")
		resolved = model_config_module.resolve_model_sampling("openai", "gpt-4o", base)
		self.assertEqual(resolved, base)


class ModelConfigFieldTests(unittest.TestCase):
	"""Field registry: provider-agnostic, complete, defaulted."""

	def test_field_ids_match_sampling_fields(self) -> None:
		self.assertEqual(
			{spec.id for spec in MODEL_CONFIG_FIELDS},
			set(SAMPLING_FIELD_IDS),
		)

	def test_fields_cover_sampling_fields(self) -> None:
		ids = [spec.id for spec in MODEL_CONFIG_FIELDS]
		self.assertEqual(
			ids,
			["num_ctx", "temperature", "top_k", "top_p", "max_tokens", "repeat_penalty"],
		)

	def test_every_field_has_display_default(self) -> None:
		for spec in MODEL_CONFIG_FIELDS:
			self.assertIsNotNone(spec.default, spec.id)

	def test_every_field_has_minimum(self) -> None:
		for spec in MODEL_CONFIG_FIELDS:
			self.assertIsNotNone(spec.minimum, spec.id)

	def test_get_model_config_fields_returns_registry(self) -> None:
		self.assertIs(model_config_module.get_model_config_fields(), MODEL_CONFIG_FIELDS)

	def test_field_by_id_map_complete(self) -> None:
		self.assertEqual(
			set(model_config_module.MODEL_FIELD_BY_ID),
			set(SAMPLING_FIELD_IDS),
		)


class EffectiveFieldValueTests(unittest.TestCase):
	"""Configure-dialog display values."""

	def setUp(self) -> None:
		_with_temp_store(self)

	def test_falls_back_to_static_default_when_unset(self) -> None:
		base = ModelSamplingConfig(num_ctx=8192, temperature=0.2, top_p=0.85, max_tokens=1024)
		value = model_config_module.effective_field_value("openai", "gpt-4o", base, "num_ctx")
		self.assertEqual(value, 8192)

	def test_prefers_pinned_value(self) -> None:
		base = ModelSamplingConfig(num_ctx=8192, temperature=0.2, top_p=0.85, max_tokens=1024)
		model_config_module.set_model_sampling(
			"openai",
			"gpt-4o",
			ModelSamplingConfig(num_ctx=2048),
		)
		value = model_config_module.effective_field_value("openai", "gpt-4o", base, "num_ctx")
		self.assertEqual(value, 2048)

	def test_unpinned_top_k_uses_static_default(self) -> None:
		base = ModelSamplingConfig(num_ctx=8192, temperature=0.2, top_p=0.85, max_tokens=1024)
		value = model_config_module.effective_field_value("openai", "gpt-4o", base, "top_k")
		self.assertEqual(value, 10)


class FallbackFieldValueTests(unittest.TestCase):
	"""Values shown next to a checked "Use default" box (P1)."""

	def setUp(self) -> None:
		_with_temp_store(self)

	def test_wire_fallback_field_uses_provider_global(self) -> None:
		base = ModelSamplingConfig(num_ctx=4096, temperature=0.5, top_p=0.9, max_tokens=512)
		spec = model_config_module.MODEL_FIELD_BY_ID["temperature"]
		value = model_config_module.fallback_field_value(base, "temperature", spec)
		self.assertEqual(value, 0.5)

	def test_pinned_only_field_uses_static_default(self) -> None:
		# top_k has no global fallback — unpinned means static default.
		base = ModelSamplingConfig(num_ctx=4096, temperature=0.5, top_p=0.9, max_tokens=512)
		spec = model_config_module.MODEL_FIELD_BY_ID["top_k"]
		value = model_config_module.fallback_field_value(base, "top_k", spec)
		self.assertEqual(value, 10)

	def test_repeat_penalty_falls_back_to_static_default(self) -> None:
		base = ModelSamplingConfig(num_ctx=4096, temperature=0.5, top_p=0.9, max_tokens=512)
		spec = model_config_module.MODEL_FIELD_BY_ID["repeat_penalty"]
		value = model_config_module.fallback_field_value(base, "repeat_penalty", spec)
		self.assertEqual(value, 0)

	def test_unknown_spec_returns_zero(self) -> None:
		base = ModelSamplingConfig(num_ctx=4096, temperature=0.5, top_p=0.9, max_tokens=512)
		self.assertEqual(model_config_module.fallback_field_value(base, "bogus", None), 0)


class ModelConfigureTitleTests(unittest.TestCase):
	"""Title helper is wx-free and translatable."""

	def test_title_format(self) -> None:
		self.assertEqual(
			model_config_module.model_configure_title("Gemma 4 E2B"),
			"Configure Gemma 4 E2B",
		)


if __name__ == "__main__":
	unittest.main()
