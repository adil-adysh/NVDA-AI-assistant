# -*- coding: utf-8 -*-
# Pylint cannot infer attributes assigned to types.ModuleType() fakes used
# to stub NVDA-internal modules (E1101 ``__name__`` false positives).
# pylint: disable=no-member
from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import sys
import types
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent
ROOT_DIR = MODULE_DIR.parent
PACKAGE_NAME = "provider_state_flow_testpkg"


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
	backend_url: str


_active_config = None


def _set_active_config(config) -> None:
	global _active_config
	_active_config = config


def _get_active_provider_config():
	return _active_config


def _get_provider_state() -> _ProviderState:
	config = _get_active_provider_config()
	backend_url = getattr(config, "base_url", getattr(config, "server_url", ""))
	return _ProviderState(provider=config.provider, model_name=config.model_name, backend_url=backend_url)


settings_module = types.ModuleType(f"{PACKAGE_NAME}.config.settings")
settings_module.get_active_provider_config = _get_active_provider_config
settings_module.get_provider_state = _get_provider_state
settings_module.get_ollama_think = lambda: False
settings_module.get_litert_think = lambda: False
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

provider_readiness_module = _load_module(
	f"{PACKAGE_NAME}.service.provider_readiness",
	ROOT_DIR / "service" / "provider_readiness.py",
)
provider_catalog_module = _load_module(
	f"{PACKAGE_NAME}.service.provider_catalog",
	ROOT_DIR / "service" / "provider_catalog.py",
)
session_state_module = _load_module(
	f"{PACKAGE_NAME}.ui.session_state",
	ROOT_DIR / "ui" / "session_state.py",
)

GeminiConfig = config_module.GeminiConfig
OpenAIConfig = config_module.OpenAIConfig
ProviderCatalogService = provider_catalog_module.ProviderCatalogService
ProviderReadinessReason = provider_readiness_module.ProviderReadinessReason
ProviderReadinessService = provider_readiness_module.ProviderReadinessService
ProviderReadinessState = provider_readiness_module.ProviderReadinessState
build_session_state = session_state_module.build_session_state
merge_session_metadata = session_state_module.merge_session_metadata


class ProviderStateFlowTests(unittest.TestCase):
	def setUp(self) -> None:
		self.readiness_service = ProviderReadinessService()

	def test_openai_missing_api_key_is_unconfigured(self) -> None:
		config = OpenAIConfig(
			provider="openai",
			model_name="gpt-4.1",
			timeout_seconds=30.0,
			enable_progress=False,
			num_ctx=0,
			max_retries=1,
			retry_backoff_seconds=0.1,
			generate_temperature=0.2,
			generate_top_k=0,
			generate_top_p=0.9,
			generate_max_tokens=512,
			api_key="",
			base_url="https://api.openai.com",
			chat_path="/v1/chat/completions",
			organization=None,
		)

		readiness = self.readiness_service.evaluate(config)

		self.assertEqual(readiness.state, ProviderReadinessState.UNCONFIGURED)
		self.assertEqual(readiness.reason, ProviderReadinessReason.MISSING_CREDENTIALS)
		self.assertFalse(readiness.can_infer)
		self.assertFalse(readiness.can_list_models)

	def test_gemini_with_api_token_is_ready(self) -> None:
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
			api_key="",
			api_token="token-value",
			base_url="https://generativelanguage.googleapis.com",
		)

		readiness = self.readiness_service.evaluate(config)

		self.assertEqual(readiness.state, ProviderReadinessState.READY)
		self.assertIsNone(readiness.reason)
		self.assertTrue(readiness.can_infer)
		self.assertTrue(readiness.can_list_models)

	def test_gemini_live_preview_model_is_invalid_for_current_workflow(self) -> None:
		config = GeminiConfig(
			provider="gemini",
			model_name="gemini-3.1-flash-live-preview",
			timeout_seconds=30.0,
			enable_progress=False,
			num_ctx=0,
			max_retries=1,
			retry_backoff_seconds=0.1,
			generate_temperature=0.2,
			generate_top_k=0,
			generate_top_p=0.9,
			generate_max_tokens=512,
			api_key="configured-key",
			api_token="",
			base_url="https://generativelanguage.googleapis.com",
		)

		readiness = self.readiness_service.evaluate(config)

		self.assertEqual(readiness.state, ProviderReadinessState.INVALID_CONFIG)
		self.assertEqual(readiness.reason, ProviderReadinessReason.UNSUPPORTED_MODEL)
		self.assertFalse(readiness.can_infer)
		self.assertTrue(readiness.can_list_models)

	def test_gemini_deep_research_preview_model_is_invalid_for_current_workflow(self) -> None:
		config = GeminiConfig(
			provider="gemini",
			model_name="deep-research-preview-04-2026",
			timeout_seconds=30.0,
			enable_progress=False,
			num_ctx=0,
			max_retries=1,
			retry_backoff_seconds=0.1,
			generate_temperature=0.2,
			generate_top_k=0,
			generate_top_p=0.9,
			generate_max_tokens=512,
			api_key="configured-key",
			api_token="",
			base_url="https://generativelanguage.googleapis.com",
		)

		readiness = self.readiness_service.evaluate(config)

		self.assertEqual(readiness.state, ProviderReadinessState.INVALID_CONFIG)
		self.assertEqual(readiness.reason, ProviderReadinessReason.UNSUPPORTED_MODEL)
		self.assertFalse(readiness.can_infer)
		self.assertTrue(readiness.can_list_models)

	def test_catalog_does_not_construct_provider_when_not_ready(self) -> None:
		config = OpenAIConfig(
			provider="openai",
			model_name="gpt-4.1",
			timeout_seconds=30.0,
			enable_progress=False,
			num_ctx=0,
			max_retries=1,
			retry_backoff_seconds=0.1,
			generate_temperature=0.2,
			generate_top_k=0,
			generate_top_p=0.9,
			generate_max_tokens=512,
			api_key="",
			base_url="https://api.openai.com",
			chat_path="/v1/chat/completions",
			organization=None,
		)
		factory_calls: list[object] = []

		def fake_factory(provider_config):
			factory_calls.append(provider_config)
			raise AssertionError("Provider factory should not be called when readiness blocks model catalog access")

		catalog = ProviderCatalogService(
			readiness_service=self.readiness_service,
			config_resolver=lambda: config,
			provider_factory=fake_factory,
		)

		self.assertEqual(catalog.list_active_models(), ())
		self.assertEqual(factory_calls, [])

	def test_session_state_projects_provider_readiness(self) -> None:
		config = OpenAIConfig(
			provider="openai",
			model_name="gpt-4.1",
			timeout_seconds=30.0,
			enable_progress=False,
			num_ctx=0,
			max_retries=1,
			retry_backoff_seconds=0.1,
			generate_temperature=0.2,
			generate_top_k=0,
			generate_top_p=0.9,
			generate_max_tokens=512,
			api_key="",
			base_url="https://api.openai.com",
			chat_path="/v1/chat/completions",
			organization=None,
		)
		_set_active_config(config)
		readiness = self.readiness_service.evaluate_active()

		session_state = build_session_state(
			lambda message: message,
			provider_state=_get_provider_state(),
			available_models=(),
			readiness=readiness,
		)
		metadata = session_state.to_metadata()

		self.assertFalse(metadata["chat_enabled"])
		self.assertEqual(metadata["provider_status"]["state"], ProviderReadinessState.UNCONFIGURED.value)
		self.assertEqual(metadata["provider_status"]["reason"], ProviderReadinessReason.MISSING_CREDENTIALS.value)
		self.assertIn("OpenAI is selected but not configured", metadata["status_message"])

	def test_merge_session_metadata_clears_stale_status_when_provider_is_ready(self) -> None:
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
			api_key="configured-key",
			api_token="",
			base_url="https://generativelanguage.googleapis.com",
		)
		_set_active_config(config)
		readiness = self.readiness_service.evaluate_active()

		session_state = build_session_state(
			lambda message: message,
			provider_state=_get_provider_state(),
			available_models=("gemini-2.5-flash",),
			readiness=readiness,
		)
		merged = merge_session_metadata(
			{"status_message": "Gemini is selected but not configured. Set an API key or bearer token in settings."},
			session_state,
		)

		self.assertNotIn("status_message", merged)
		self.assertTrue(merged["chat_enabled"])
		self.assertEqual(merged["provider_status"]["state"], ProviderReadinessState.READY.value)


if __name__ == "__main__":
	unittest.main()
