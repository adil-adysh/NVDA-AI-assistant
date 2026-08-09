# -*- coding: utf-8 -*-
# Pylint cannot infer attributes assigned to types.ModuleType() fakes used
# to stub NVDA-internal modules (E1101 ``__name__`` false positives).
# Test files deliberately duplicate the self-contained synthetic-package
# bootstrap so each suite can run standalone (R0801).
# pylint: disable=no-member,duplicate-code
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent
ROOT_DIR = MODULE_DIR.parent
PACKAGE_NAME = "settings_activation_testpkg"


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
_register_package(f"{PACKAGE_NAME}.providers", ROOT_DIR / "providers")

log_handler_module = types.ModuleType("logHandler")
log_handler_module.log = types.SimpleNamespace(
	debug=lambda *args, **kwargs: None,
	warning=lambda *args, **kwargs: None,
	exception=lambda *args, **kwargs: None,
)
sys.modules["logHandler"] = log_handler_module

language_handler_module = types.ModuleType("languageHandler")
language_handler_module.getLanguage = lambda: "en"
sys.modules["languageHandler"] = language_handler_module


class _NoOpStore:
	def __init__(self, *args, **kwargs) -> None:
		pass


yaml_store_module = types.ModuleType(f"{PACKAGE_NAME}.config.yaml_store")
yaml_store_module.YamlConfigStore = _NoOpStore
sys.modules[yaml_store_module.__name__] = yaml_store_module

settings_module = _load_module(
	f"{PACKAGE_NAME}.config.settings",
	ROOT_DIR / "config" / "settings.py",
)
config_module = _load_module(
	f"{PACKAGE_NAME}.providers.config",
	ROOT_DIR / "providers" / "config.py",
)


class _FakeStore:
	def __init__(self) -> None:
		self.data: dict[str, object] = {}

	def get(self, key: str, default: object = None) -> object:
		return self.data.get(key, default)

	def set(self, key: str, value: object) -> None:
		self.data[key] = value

	def set_many(self, values: dict[str, object]) -> None:
		self.data.update(values)


settings_module._config_store = _FakeStore()  # pylint: disable=protected-access

set_openai_compat_config = settings_module.set_openai_compat_config


def _make_config(
	provider: str,
	model_name: str = "gpt-4o-mini",
	base_url: str = "https://api.openai.com",
	api_key: str = "sk-test",
	chat_path: str = "/v1/chat/completions",
):
	return config_module.OpenAICompatConfig(
		provider=provider,
		model_name=model_name,
		base_url=base_url,
		api_key=api_key,
		chat_path=chat_path,
		timeout_seconds=30.0,
		enable_progress=False,
		num_ctx=8192,
		max_retries=2,
		retry_backoff_seconds=0.75,
		generate_temperature=0.2,
		generate_top_k=10,
		generate_top_p=0.85,
		generate_max_tokens=1024,
		think=False,
	)


class SetOpenAICompatConfigActivationTests(unittest.TestCase):
	"""Persistence boundaries: provider config vs active selection (spec 44)."""

	def setUp(self) -> None:
		store = _FakeStore()
		store.data["provider"] = "ollama"
		store.data["ollamaModelName"] = "ministral-3:3b"
		store.data["ollamaServerUrl"] = "http://127.0.0.1:11434"
		settings_module._config_store = store  # pylint: disable=protected-access

	def test_configure_does_not_change_active_provider(self) -> None:
		"""Configure dialogs persist with activate=False -> provider key untouched."""
		config = _make_config("openai", model_name="gpt-4o-mini", api_key="sk-new")
		set_openai_compat_config(config, activate=False)

		store = settings_module._config_store  # pylint: disable=protected-access
		self.assertEqual(store.data["provider"], "ollama")
		# OpenAI's own keys were persisted.
		self.assertEqual(store.data["openaiModelName"], "gpt-4o-mini")
		self.assertEqual(store.data["openaiBaseUrl"], "https://api.openai.com")
		self.assertEqual(store.data["openaiApiKey"], "sk-new")

	def test_configure_persists_provider_config_without_model_leakage(self) -> None:
		"""Provider configuration and model state stay in their own keys."""
		config = _make_config("openai", model_name="gpt-4o-mini")
		set_openai_compat_config(config, activate=False)

		store = settings_module._config_store  # pylint: disable=protected-access
		# Model name lives under the provider prefix, never a generic key.
		self.assertEqual(store.data["openaiModelName"], "gpt-4o-mini")
		self.assertNotIn("modelName", store.data)
		# Active provider unchanged.
		self.assertEqual(store.data["provider"], "ollama")

	def test_legacy_activation_still_switches_provider(self) -> None:
		"""activate=True (historical default) switches the active provider."""
		config = _make_config("gemini", model_name="gemini-flash", api_key="gk")
		set_openai_compat_config(config, activate=True)

		store = settings_module._config_store  # pylint: disable=protected-access
		self.assertEqual(store.data["provider"], "gemini")
		self.assertEqual(store.data["geminiModelName"], "gemini-flash")

	def test_default_activation_matches_legacy_behavior(self) -> None:
		"""Calling without activate keeps the historical semantics."""
		config = _make_config("litert-lm", model_name="gemma", base_url="http://127.0.0.1:9379", api_key="")
		set_openai_compat_config(config)

		store = settings_module._config_store  # pylint: disable=protected-access
		self.assertEqual(store.data["provider"], "litert-lm")
		self.assertEqual(store.data["litertModelName"], "gemma")
		self.assertEqual(store.data["litertServerUrl"], "http://127.0.0.1:9379")

	def test_ollama_configure_keeps_shared_and_provider_keys(self) -> None:
		config = _make_config(
			"ollama",
			model_name="ministral-3:3b",
			base_url="http://127.0.0.1:11434",
			api_key="",
		)
		set_openai_compat_config(config, activate=False)
		store = settings_module._config_store  # pylint: disable=protected-access
		self.assertEqual(store.data["provider"], "ollama")
		self.assertEqual(store.data["ollamaModelName"], "ministral-3:3b")
		self.assertEqual(store.data["ollamaServerUrl"], "http://127.0.0.1:11434")
		# Shared sampling values are persisted alongside.
		self.assertEqual(store.data["numCtx"], 8192)


if __name__ == "__main__":
	unittest.main()
