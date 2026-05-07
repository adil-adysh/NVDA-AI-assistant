# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent
ROOT_DIR = MODULE_DIR.parent
PACKAGE_NAME = "gemini_provider_testpkg"


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
_register_package(f"{PACKAGE_NAME}.providers", ROOT_DIR / "providers")
_register_package(f"{PACKAGE_NAME}.providers.adapters", ROOT_DIR / "providers" / "adapters")
_register_package(f"{PACKAGE_NAME}.core", ROOT_DIR / "core")
_register_package(f"{PACKAGE_NAME}.service", ROOT_DIR / "service")

canonical_module = types.ModuleType(f"{PACKAGE_NAME}.core.canonical")
canonical_module.Message = dict
canonical_module.Tool = dict
sys.modules[canonical_module.__name__] = canonical_module

messages_module = types.ModuleType(f"{PACKAGE_NAME}.core.messages")
messages_module.ChatMessage = object
messages_module.LLMResponse = object
messages_module.SummaryResponse = object
sys.modules[messages_module.__name__] = messages_module

tooling_module = types.ModuleType(f"{PACKAGE_NAME}.core.tooling")
tooling_module.ToolCall = dict
sys.modules[tooling_module.__name__] = tooling_module

tools_module = types.ModuleType(f"{PACKAGE_NAME}.tools")
tools_module.build_function_tool_definition = lambda *args, **kwargs: {}
tools_module.normalize_tool_calls = lambda calls: calls
sys.modules[tools_module.__name__] = tools_module

provider_readiness_module = _load_module(
    f"{PACKAGE_NAME}.service.provider_readiness",
    ROOT_DIR / "service" / "provider_readiness.py",
)


gemini_module = types.ModuleType(f"{PACKAGE_NAME}.gemini")


class _FakeGeminiClientError(RuntimeError):
    pass


class _FakeGeminiAPIError(_FakeGeminiClientError):
    def __init__(self, status_code: int, body: str, error=None) -> None:
        super().__init__(body)
        self.status_code = status_code
        self.body = body
        self.details = error or body


class _FakeGeminiModel:
    def __init__(self, name: str, methods: list[str], display_name: str | None = None) -> None:
        self.name = name
        self.supported_generation_methods = methods
        self.display_name = display_name or name.split("/")[-1]
        self.description = None
        self.input_token_limit = None
        self.output_token_limit = None
        self.temperature = None
        self.top_p = None
        self.top_k = None
        self.max_temperature = None
        self.thinking = False
        self.raw = {"name": name, "supportedGenerationMethods": methods}


class _FakeListModelsResponse:
    def __init__(self, models, next_page_token=None) -> None:
        self.models = models
        self.next_page_token = next_page_token


class _FakeGeminiClient:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    def list_models(self, page_size=100, page_token=None):
        return _FakeListModelsResponse(
            [
                _FakeGeminiModel("models/gemini-3.1-flash-live-preview", ["bidiGenerateContent"]),
                _FakeGeminiModel("models/deep-research-preview-04-2026", ["interactions"]),
                _FakeGeminiModel("models/gemini-2.5-flash", ["generateContent", "streamGenerateContent"]),
            ]
        )


gemini_module.GeminiClient = _FakeGeminiClient
gemini_module.GeminiClientError = _FakeGeminiClientError
gemini_module.GeminiAPIError = _FakeGeminiAPIError
sys.modules[gemini_module.__name__] = gemini_module

config_module = _load_module(
    f"{PACKAGE_NAME}.providers.config",
    ROOT_DIR / "providers" / "config.py",
)
interfaces_module = _load_module(
    f"{PACKAGE_NAME}.providers.interfaces",
    ROOT_DIR / "providers" / "interfaces.py",
)
_load_module(
    f"{PACKAGE_NAME}.gemini.types",
    ROOT_DIR / "gemini" / "types.py",
)
provider_module = _load_module(
    f"{PACKAGE_NAME}.providers.adapters.gemini",
    ROOT_DIR / "providers" / "adapters" / "gemini.py",
)

GeminiConfig = config_module.GeminiConfig
GeminiProvider = provider_module.GeminiProvider
UnsupportedModelError = interfaces_module.UnsupportedModelError


class GeminiProviderModelCatalogTests(unittest.TestCase):
    def _provider(self, model_name: str) -> GeminiProvider:
        return GeminiProvider(
            GeminiConfig(
                provider="gemini",
                model_name=model_name,
                timeout_seconds=30.0,
                enable_streaming=True,
                enable_progress=False,
                num_ctx=0,
                max_retries=1,
                retry_backoff_seconds=0.1,
                generate_temperature=0.2,
                generate_top_k=0,
                generate_top_p=0.9,
                generate_max_tokens=512,
                api_key="test-key",
                api_token=None,
                base_url="https://generativelanguage.googleapis.com",
            )
        )

    def test_list_models_still_works_when_selected_model_is_live_preview(self) -> None:
        provider = self._provider("gemini-3.1-flash-live-preview")

        models = provider.list_models()

        self.assertEqual([model.id for model in models], ["gemini-2.5-flash"])

    def test_selected_live_preview_model_is_rejected_at_execution_time(self) -> None:
        provider = self._provider("gemini-3.1-flash-live-preview")

        with self.assertRaises(UnsupportedModelError):
            provider._resolve_model()

    def test_list_models_still_works_when_selected_model_is_interactions_only_preview(self) -> None:
        provider = self._provider("deep-research-preview-04-2026")

        models = provider.list_models()

        self.assertEqual([model.id for model in models], ["gemini-2.5-flash"])

    def test_selected_interactions_only_preview_model_is_rejected_at_execution_time(self) -> None:
        provider = self._provider("deep-research-preview-04-2026")

        with self.assertRaises(UnsupportedModelError):
            provider._resolve_model()


if __name__ == "__main__":
    unittest.main()
