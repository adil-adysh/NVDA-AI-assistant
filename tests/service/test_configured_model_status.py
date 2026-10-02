# -*- coding: utf-8 -*-
"""Tests for configured model status and provider authority evaluation."""
from __future__ import annotations

from dataclasses import dataclass
import sys
import types
import unittest
from unittest import mock

from tests.support import ADDON_ROOT, load_module as _load_module, register_package as _register_package


ROOT_DIR = ADDON_ROOT
MODULE_DIR = ROOT_DIR / "service"
PACKAGE_NAME = "configured_model_status_testpkg"

_register_package(PACKAGE_NAME, ROOT_DIR)
_register_package(f"{PACKAGE_NAME}.config", ROOT_DIR / "config")
_register_package(f"{PACKAGE_NAME}.providers", ROOT_DIR / "providers")
_register_package(f"{PACKAGE_NAME}.service", ROOT_DIR / "service")
_register_package(f"{PACKAGE_NAME}.ui", ROOT_DIR / "ui")

config_module = _load_module(
	f"{PACKAGE_NAME}.providers.config",
	ROOT_DIR / "providers" / "config.py",
)


@dataclass(frozen=True)
class _ProviderState:
	provider: str
	model_name: str
	backend_url: str = ""


_active_config = None


def _get_active_provider_config():
	return _active_config


def _get_provider_state() -> _ProviderState:
	if _active_config is None:
		return _ProviderState(provider="openai", model_name="")
	return _ProviderState(
		provider=_active_config.provider,
		model_name=_active_config.model_name,
		backend_url=getattr(_active_config, "base_url", ""),
	)


settings_module = types.ModuleType(f"{PACKAGE_NAME}.config.settings")
settings_module.get_active_provider_config = _get_active_provider_config
settings_module.get_provider_state = _get_provider_state
settings_module.get_provider = lambda: "openai"
settings_module.get_think = lambda _provider, _model: False
settings_module.build_provider_config = lambda provider_id: types.SimpleNamespace(provider=provider_id)
settings_module.get_enabled_providers = lambda: ("openai", "gemini", "litert-lm")
settings_module.save = lambda: None
settings_module.set_provider = lambda p: None
settings_module.set_enabled_providers = lambda ep: None
settings_module.set_openai_compat_config = lambda p, c: None
settings_module.get_image_mime_type = lambda: "image/jpeg"
settings_module.get_litert_model_name = lambda: "gemma-4-e2b-cpu"
settings_module.set_litert_model_name = lambda m: None
settings_module.__getattr__ = lambda name: (lambda *a, **kw: None)
sys.modules[settings_module.__name__] = settings_module

state_module = types.ModuleType(f"{PACKAGE_NAME}.config.state")
state_module.ProviderState = _ProviderState
sys.modules[state_module.__name__] = state_module

factory_module = types.ModuleType(f"{PACKAGE_NAME}.providers.factory")
factory_module.ProviderFactory = types.SimpleNamespace(create_provider=lambda config: None)
sys.modules[factory_module.__name__] = factory_module

intent_module = types.ModuleType(f"{PACKAGE_NAME}.ui.intent")
intent_module.AttentionPolicy = str
intent_module.FocusTarget = str
intent_module.InteractionMode = str
sys.modules[intent_module.__name__] = intent_module

_load_module(f"{PACKAGE_NAME}.core.canonical", ROOT_DIR / "core" / "canonical.py")
_load_module(f"{PACKAGE_NAME}.core.messages", ROOT_DIR / "core" / "messages.py")
_load_module(f"{PACKAGE_NAME}.config.enabled_models", ROOT_DIR / "config" / "enabled_models.py")
cache_module = _load_module(f"{PACKAGE_NAME}.service.model_cache", ROOT_DIR / "service" / "model_cache.py")
provider_readiness_module = _load_module(
	f"{PACKAGE_NAME}.service.provider_readiness",
	ROOT_DIR / "service" / "provider_readiness.py",
)
session_state_module = _load_module(
	f"{PACKAGE_NAME}.ui.session_state",
	ROOT_DIR / "ui" / "session_state.py",
)

LiteRTConfig = config_module.LiteRTConfig
OpenAICompatConfig = config_module.OpenAICompatConfig
GeminiConfig = config_module.GeminiConfig
ProviderReadinessReason = provider_readiness_module.ProviderReadinessReason
ProviderReadinessService = provider_readiness_module.ProviderReadinessService
ProviderReadinessState = provider_readiness_module.ProviderReadinessState
ModelCatalogAuthority = provider_readiness_module.ModelCatalogAuthority
ConfiguredModelState = provider_readiness_module.ConfiguredModelState
CatalogState = cache_module.CatalogState
ModelCatalogSnapshot = cache_module.ModelCatalogSnapshot
ProviderModelInfo = _load_module(f"{PACKAGE_NAME}.providers.interfaces", ROOT_DIR / "providers" / "interfaces.py").ProviderModelInfo
build_provider_status_message = session_state_module.build_provider_status_message


class ConfiguredModelStatusTests(unittest.TestCase):
	def setUp(self) -> None:
		self.service = ProviderReadinessService()

	def test_empty_model_name_reports_missing_model(self) -> None:
		config = OpenAICompatConfig(
			provider="openai",
			model_name="",
			timeout_seconds=30.0,
			enable_progress=False,
			num_ctx=0,
			max_retries=1,
			retry_backoff_seconds=0.1,
			generate_temperature=0.2,
			generate_top_k=0,
			generate_top_p=0.9,
			generate_max_tokens=512,
			api_key="key",
			base_url="https://api.openai.com",
			chat_path="/v1/chat/completions",
		)
		readiness = self.service.evaluate(config)
		self.assertEqual(readiness.state, ProviderReadinessState.UNCONFIGURED)
		self.assertEqual(readiness.reason, ProviderReadinessReason.MISSING_MODEL)
		self.assertFalse(readiness.can_infer)
		self.assertIsNotNone(readiness.model_status)
		self.assertEqual(readiness.model_status.state, ConfiguredModelState.NOT_CONFIGURED)

	def test_disabled_model_reports_model_disabled(self) -> None:
		enabled_models_mod = sys.modules[f"{PACKAGE_NAME}.config.enabled_models"]
		store = enabled_models_mod.ModelVisibilityStore()
		store.set_model_visible("openai", "gpt-4o-mini", False)

		try:
			config = OpenAICompatConfig(
				provider="openai",
				model_name="gpt-4o-mini",
				timeout_seconds=30.0,
				enable_progress=False,
				num_ctx=0,
				max_retries=1,
				retry_backoff_seconds=0.1,
				generate_temperature=0.2,
				generate_top_k=0,
				generate_top_p=0.9,
				generate_max_tokens=512,
				api_key="key",
				base_url="https://api.openai.com",
				chat_path="/v1/chat/completions",
			)
			readiness = self.service.evaluate(config)
			self.assertEqual(readiness.state, ProviderReadinessState.INVALID_CONFIG)
			self.assertEqual(readiness.reason, ProviderReadinessReason.MODEL_DISABLED)
			self.assertFalse(readiness.can_infer)
			self.assertEqual(readiness.model_status.state, ConfiguredModelState.DISABLED)

			msg = build_provider_status_message(lambda m: m, readiness)
			self.assertIn("disabled", msg.lower())
		finally:
			store.set_model_visible("openai", "gpt-4o-mini", True)

	def test_litert_uninstalled_model_reports_unavailable(self) -> None:
		fake_supervisor = types.SimpleNamespace(is_running=True, is_adopted=False)
		ready_snapshot = ModelCatalogSnapshot(
			provider_id="litert-lm",
			state=CatalogState.READY,
			models=(
				ProviderModelInfo(id="gemma-4-e2b-cpu", provider="litert-lm"),
			),
			version=1,
		)

		config = LiteRTConfig(
			provider="litert-lm",
			model_name="gemma-4-12b",
			timeout_seconds=30.0,
			enable_progress=False,
			num_ctx=0,
			max_retries=1,
			retry_backoff_seconds=0.1,
			generate_temperature=0.2,
			generate_top_k=0,
			generate_top_p=0.9,
			generate_max_tokens=512,
			base_url="http://127.0.0.1:9379",
		)

		with mock.patch.object(
			provider_readiness_module,
			"get_litert_supervisor",
			return_value=fake_supervisor,
		), mock.patch.object(
			cache_module.model_catalog_cache,
			"get_snapshot",
			return_value=ready_snapshot,
		):
			readiness = self.service.evaluate(config)

		self.assertEqual(readiness.state, ProviderReadinessState.INVALID_CONFIG)
		self.assertEqual(readiness.reason, ProviderReadinessReason.MODEL_UNAVAILABLE)
		self.assertFalse(readiness.can_infer)
		self.assertEqual(readiness.model_status.state, ConfiguredModelState.UNAVAILABLE)
		self.assertEqual(readiness.model_status.authority, ModelCatalogAuthority.AUTHORITATIVE)

		msg = build_provider_status_message(lambda m: m, readiness)
		self.assertIn("not available", msg.lower())

	def test_litert_installed_model_reports_valid(self) -> None:
		fake_supervisor = types.SimpleNamespace(is_running=True, is_adopted=False)
		ready_snapshot = ModelCatalogSnapshot(
			provider_id="litert-lm",
			state=CatalogState.READY,
			models=(
				ProviderModelInfo(id="gemma-4-e2b-cpu", provider="litert-lm"),
			),
			version=1,
		)

		config = LiteRTConfig(
			provider="litert-lm",
			model_name="gemma-4-e2b-cpu",
			timeout_seconds=30.0,
			enable_progress=False,
			num_ctx=0,
			max_retries=1,
			retry_backoff_seconds=0.1,
			generate_temperature=0.2,
			generate_top_k=0,
			generate_top_p=0.9,
			generate_max_tokens=512,
			base_url="http://127.0.0.1:9379",
		)

		with mock.patch.object(
			provider_readiness_module,
			"get_litert_supervisor",
			return_value=fake_supervisor,
		), mock.patch.object(
			cache_module.model_catalog_cache,
			"get_snapshot",
			return_value=ready_snapshot,
		):
			readiness = self.service.evaluate(config)

		self.assertEqual(readiness.state, ProviderReadinessState.READY)
		self.assertIsNone(readiness.reason)
		self.assertTrue(readiness.can_infer)
		self.assertEqual(readiness.model_status.state, ConfiguredModelState.VALID)


	def test_cloud_provider_valid_model_has_advisory_authority(self) -> None:
		config = GeminiConfig(
			provider="gemini",
			model_name="gemini-2.5-flash",
			timeout_seconds=30.0,
			enable_progress=False,
			num_ctx=0,
			max_retries=1,
			retry_backoff_seconds=0.1,
			generate_temperature=0.2,
			generate_top_k=0,
			generate_top_p=0.9,
			generate_max_tokens=512,
			api_key="valid-key",
			api_token="",
			base_url="https://generativelanguage.googleapis.com",
		)
		readiness = self.service.evaluate(config)
		self.assertEqual(readiness.state, ProviderReadinessState.READY)
		self.assertTrue(readiness.can_infer)
		self.assertIsNotNone(readiness.model_status)
		self.assertEqual(readiness.model_status.state, ConfiguredModelState.VALID)
		self.assertEqual(readiness.model_status.authority, ModelCatalogAuthority.ADVISORY)

	def test_cloud_provider_unsupported_model_reports_unsupported(self) -> None:
		config = GeminiConfig(
			provider="gemini",
			model_name="gemini-2.0-flash-live-preview",
			timeout_seconds=30.0,
			enable_progress=False,
			num_ctx=0,
			max_retries=1,
			retry_backoff_seconds=0.1,
			generate_temperature=0.2,
			generate_top_k=0,
			generate_top_p=0.9,
			generate_max_tokens=512,
			api_key="valid-key",
			api_token="",
			base_url="https://generativelanguage.googleapis.com",
		)
		readiness = self.service.evaluate(config)
		self.assertEqual(readiness.state, ProviderReadinessState.INVALID_CONFIG)
		self.assertEqual(readiness.reason, ProviderReadinessReason.UNSUPPORTED_MODEL)
		self.assertFalse(readiness.can_infer)
		self.assertEqual(readiness.model_status.state, ConfiguredModelState.UNAVAILABLE)


if __name__ == "__main__":
	unittest.main()
