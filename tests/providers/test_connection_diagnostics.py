from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.support import load_addon_module

adapter = load_addon_module("providers.adapters.openai_compat", namespace="connection_diagnostics_testpkg")


@pytest.mark.parametrize("provider", ["openai", "gemini", "ollama", "litert-lm", "llama-cpp-server"])
def test_connection_checks_configured_endpoint_without_runtime_catalog_or_ollama_probe(provider):
	instance = object.__new__(adapter.OpenAICompatProvider)
	instance._provider_id = provider
	instance._client = SimpleNamespace(list_models=lambda: [{"id": "example"}])
	# Local model metadata and persisted catalogs cannot prove a connection.
	instance.list_models = Mock(side_effect=AssertionError("must check remote endpoint"))
	assert instance.check_connection() == 1


@pytest.mark.parametrize("payload", [None, {}, [{"name": "not a model"}]])
def test_connection_rejects_malformed_models_response(payload):
	instance = object.__new__(adapter.OpenAICompatProvider)
	instance._client = SimpleNamespace(list_models=lambda: payload)
	with pytest.raises(adapter.LLMProviderError, match="model"):
		instance.check_connection()


@pytest.mark.parametrize("provider", ["openai", "gemini", "litert-lm", "llama-cpp-server"])
def test_non_ollama_providers_do_not_probe_unauthenticated_ollama_endpoint(provider):
	instance = object.__new__(adapter.OpenAICompatProvider)
	instance._provider_id = provider
	instance._is_ollama = None
	instance._native_client = Mock(side_effect=AssertionError("wrong provider protocol"))
	assert not instance._detect_ollama()
	instance._native_client.assert_not_called()


def test_current_openai_family_has_vision_and_reasoning():
	instance = object.__new__(adapter.OpenAICompatProvider)
	instance._provider_id = "openai"
	instance._config = SimpleNamespace(provider="openai")
	info = instance._capabilities_for_model("gpt-6.2-sol")
	assert {"image_input", "thinking", "tools", "chat"} <= set(info.capabilities)


def test_explicit_server_capabilities_are_not_overridden_by_model_name():
	instance = object.__new__(adapter.OpenAICompatProvider)
	instance._provider_id = "openai"
	instance._config = SimpleNamespace(provider="openai")
	info = instance._capabilities_for_model("gpt-4o", {"chat"})
	assert "image_input" not in info.capabilities
	assert "tools" not in info.capabilities


@pytest.mark.parametrize("model", ["text-embedding-3-small", "gpt-4o-transcribe", "gpt-4o-mini-tts", "gpt-realtime", "gpt-image-1", "omni-moderation-latest"])
def test_openai_catalog_does_not_offer_non_chat_models(model):
	instance = object.__new__(adapter.OpenAICompatProvider)
	instance._provider_id = "openai"
	instance._config = SimpleNamespace(provider="openai")
	instance._client = SimpleNamespace(list_models=lambda: [{"id": model}, {"id": "gpt-4.1"}])
	assert [item.id for item in instance._list_models_openai_compat()] == ["gpt-4.1"]


@pytest.mark.parametrize("model", ["o1-mini", "o1-preview", "o3-mini"])
def test_text_only_reasoning_models_are_not_marked_as_vision(model):
	instance = object.__new__(adapter.OpenAICompatProvider)
	instance._provider_id = "openai"
	instance._config = SimpleNamespace(provider="openai")
	assert "image_input" not in instance._capabilities_for_model(model).capabilities


def test_explicit_empty_capabilities_remain_authoritative():
	assert adapter._extract_advertised_capabilities({"capabilities": []}) == set()
	assert adapter._extract_advertised_capabilities({"capabilities": ["image_input", "chat"]}) == {"image_input", "chat"}
