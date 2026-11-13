from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.support import load_addon_module

manager = load_addon_module("providers.model_manager", namespace="catalog_refresh_tests")
adapter = load_addon_module("providers.adapters.openai_compat", namespace="catalog_refresh_tests")
catalog_service = load_addon_module("service.provider_catalog", namespace="catalog_refresh_tests")


def test_cloud_manager_observes_central_cache_invalidation():
    cache = Mock()
    cache.get_models.return_value = (SimpleNamespace(id="old", display_name="old", capabilities=("chat",)),)
    cache.get_models_or_empty.return_value = cache.get_models.return_value
    instance = manager.CloudModelManagerAdapter("openai", Mock(), SimpleNamespace(model_name="old"), Mock(), model_cache=cache)
    assert instance.list_managed_models()[0].id == "old"
    cache.get_models.return_value = (SimpleNamespace(id="new", display_name="new", capabilities=("chat",)),)
    cache.get_models_or_empty.return_value = cache.get_models.return_value
    assert instance.list_managed_models()[0].id == "new"


@pytest.mark.parametrize("method,client_attr,operation", [
    ("_list_models_openai_compat", "_client", "list_models"),
    ("_list_models_ollama_native", "_native_client", "get"),
])
def test_discovery_failure_is_not_successful_empty_catalog(method, client_attr, operation):
    instance = object.__new__(adapter.OpenAICompatProvider)
    client = Mock()
    getattr(client, operation).side_effect = RuntimeError("offline")
    setattr(instance, client_attr, (lambda: client) if client_attr == "_native_client" else client)
    with pytest.raises(adapter.LLMProviderError, match="offline"):
        getattr(instance, method)()


@pytest.mark.parametrize("provider_id", ["litert-lm", "llama-cpp-server"])
def test_local_catalog_discovery_does_not_require_running_server(provider_id):
    readiness = Mock()
    readiness.evaluate.return_value = SimpleNamespace(can_list_models=False)
    provider = Mock()
    provider.list_models.return_value = ()
    factory = Mock(return_value=provider)
    service = catalog_service.ProviderCatalogService(readiness_service=readiness, provider_factory=factory)
    assert service.discover_models(SimpleNamespace(provider=provider_id)) == ()
    readiness.evaluate.assert_not_called()
    provider.close.assert_called_once()


def test_unconfigured_cloud_discovery_is_retryable_failure():
    readiness = Mock()
    readiness.evaluate.return_value = SimpleNamespace(can_list_models=False)
    service = catalog_service.ProviderCatalogService(readiness_service=readiness)
    with pytest.raises(adapter.LLMProviderError, match="Configure"):
        service.discover_models(SimpleNamespace(provider="openai"))


def test_litert_authoritative_discovery_reports_worker_unavailability(monkeypatch):
    runtime = load_addon_module("providers.runtime.server", namespace="catalog_refresh_tests")
    supervisor = runtime.LiteRTServerSupervisor()
    monkeypatch.setattr(supervisor, "_get_worker_client", lambda **kwargs: None)
    with pytest.raises(runtime.LiteRTServerError, match="worker"):
        supervisor.list_server_models(strict=True)
