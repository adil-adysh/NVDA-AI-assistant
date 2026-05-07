# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent
ROOT_DIR = MODULE_DIR.parent
PACKAGE_NAME = "openai_provider_testpkg"


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

openai_module = types.ModuleType(f"{PACKAGE_NAME}.openai")


class _FakeOpenAIClientError(RuntimeError):
	pass


class _FakeOpenAIClientConfigurationError(_FakeOpenAIClientError):
	pass


class _FakeOpenAIClient:
	def __init__(self, **kwargs) -> None:
		self.kwargs = kwargs


openai_module.OpenAIClient = _FakeOpenAIClient
openai_module.OpenAIClientError = _FakeOpenAIClientError
sys.modules[openai_module.__name__] = openai_module

openai_errors_module = types.ModuleType(f"{PACKAGE_NAME}.openai.errors")
openai_errors_module.OpenAIClientConfigurationError = _FakeOpenAIClientConfigurationError
openai_errors_module.OpenAIClientError = _FakeOpenAIClientError
sys.modules[openai_errors_module.__name__] = openai_errors_module

config_module = _load_module(
	f"{PACKAGE_NAME}.providers.config",
	ROOT_DIR / "providers" / "config.py",
)
interfaces_module = _load_module(
	f"{PACKAGE_NAME}.providers.interfaces",
	ROOT_DIR / "providers" / "interfaces.py",
)
provider_module = _load_module(
	f"{PACKAGE_NAME}.providers.adapters.openai",
	ROOT_DIR / "providers" / "adapters" / "openai.py",
)

OpenAIConfig = config_module.OpenAIConfig
OpenAIProvider = provider_module.OpenAIProvider


class OpenAIProviderCapabilityTests(unittest.TestCase):
	def _provider(self, model_name: str) -> OpenAIProvider:
		return OpenAIProvider(
			OpenAIConfig(
				provider="openai",
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
				base_url="https://api.openai.com",
				chat_path="/v1/chat/completions",
				organization=None,
			)
		)

	def test_supports_image_description_for_current_vision_families(self) -> None:
		for model_name in (
			"gpt-4-turbo",
			"gpt-4-vision-preview",
			"o4-mini",
			"chatgpt-4o-latest",
			"ft:gpt-4o-mini:example-org:custom",
		):
			with self.subTest(model_name=model_name):
				self.assertTrue(self._provider(model_name).supports_image_description())

	def test_metadata_input_modalities_enable_image_support(self) -> None:
		provider = self._provider("custom-alias")
		model_info = provider._normalize_model_info(
			{
				"id": "custom-alias",
				"input_modalities": ["text", "image"],
				"output_modalities": ["text"],
			}
		)

		self.assertTrue(model_info.supports("image_input"))
		self.assertTrue(model_info.supports("text_input"))
		self.assertTrue(model_info.supports("text_output"))

	def test_metadata_architecture_modalities_enable_image_support(self) -> None:
		provider = self._provider("custom-architecture-alias")
		model_info = provider._normalize_model_info(
			{
				"id": "custom-architecture-alias",
				"architecture": {
					"input_modalities": ["text", "image"],
					"output_modalities": ["text", "audio"],
				},
			}
		)

		self.assertTrue(model_info.supports("image_input"))
		self.assertTrue(model_info.supports("audio_output"))


if __name__ == "__main__":
	unittest.main()
