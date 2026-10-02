# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tests.support import ADDON_ROOT, load_module, register_package

NAMESPACE = "background_provider_ready_testpkg"
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


_stub(
	"providers.interfaces",
	LLMProviderError=_LLMProviderError,
	ProviderConfigurationError=_ProviderConfigurationError,
)
class _LiteRTServerError(RuntimeError):
	pass


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


class EnsureProviderServerReadyTests(unittest.TestCase):
	def test_non_llama_provider_is_noop(self) -> None:
		with patch.object(background, "get_provider", return_value="openai"):
			# Should return immediately without error
			background.ensure_provider_server_ready()

	def test_falls_back_to_catalog_when_configured_model_is_unknown(self) -> None:
		config = SimpleNamespace(
			provider="llama-cpp-server",
			model_name="unknown-model",
		)
		preset_record = SimpleNamespace(model_id="preset-qwen")
		mock_manager = MagicMock()
		mock_manager.find_record.return_value = None
		mock_manager._catalog.list_records.return_value = [preset_record]

		set_model_calls: list[str] = []
		refreshed: list[str] = []

		mock_cache = SimpleNamespace(refresh_async=refreshed.append)

		settings_mod = sys.modules[f"{NAMESPACE}.config.settings"]
		model_cache_mod = sys.modules[f"{NAMESPACE}.service.model_cache"]

		with patch.object(background, "get_provider", return_value="llama-cpp-server"), \
			 patch.object(settings_mod, "get_active_provider_config", return_value=config), \
			 patch.object(settings_mod, "set_model_name", side_effect=set_model_calls.append), \
			 patch.object(background, "LlamaCppModelManager", return_value=mock_manager), \
			 patch.object(model_cache_mod, "model_catalog_cache", mock_cache):
			background.ensure_provider_server_ready()

			# Verified fallback occurred
			mock_manager.ensure_running.assert_called_once_with(preset_record, on_progress=None)
			self.assertEqual(set_model_calls, ["preset-qwen"])
			self.assertEqual(refreshed, ["llama-cpp-server"])

	def test_raises_when_catalog_has_no_records_for_unknown_model(self) -> None:
		config = SimpleNamespace(
			provider="llama-cpp-server",
			model_name="unknown-model",
		)
		mock_manager = MagicMock()
		mock_manager.find_record.return_value = None
		mock_manager._catalog.list_records.return_value = []

		settings_mod = sys.modules[f"{NAMESPACE}.config.settings"]

		with patch.object(background, "get_provider", return_value="llama-cpp-server"), \
			 patch.object(settings_mod, "get_active_provider_config", return_value=config), \
			 patch.object(background, "LlamaCppModelManager", return_value=mock_manager):
			with self.assertRaises(background.LLMProviderError):
				background.ensure_provider_server_ready()


if __name__ == "__main__":
	unittest.main()
