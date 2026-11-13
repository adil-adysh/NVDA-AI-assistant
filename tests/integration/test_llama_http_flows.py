from types import SimpleNamespace
import threading

import pytest

from tests.support import load_addon_module
from tests.support.llama_http import router_http


def supervisor(port):
    module = load_addon_module("providers.runtime.llama_server", namespace="llama_http_flows")
    return module.LlamaServerSupervisor(host="127.0.0.1", port=port, native_supervisor=SimpleNamespace())


def test_router_catalog_uses_status_endpoint_with_legacy_404_fallback():
    with router_http() as http:
        runtime = supervisor(http.port)
        assert runtime.list_models(refresh=True)[0]["status"]["value"] == "unloaded"
        assert [path for _, path, _ in http.requests] == ["/models"]
        http.status = 404
        assert runtime.list_models(refresh=True)[0]["id"] == "a"
        assert [path for _, path, _ in http.requests][-2:] == ["/models", "/v1/models"]


@pytest.mark.parametrize("failure", ["http", "json", "encoding", "schema", "invalid_rows"])
def test_bad_catalog_retains_snapshot_and_recovery_clears_error(failure):
    with router_http() as http:
        runtime = supervisor(http.port)
        assert runtime.list_models(refresh=True)[0]["id"] == "a"
        if failure == "http":
            http.status = 503
        elif failure == "json":
            http.payload = b"not json"
        elif failure == "encoding":
            http.payload = b"\xff"
        elif failure == "schema":
            http.payload = {"models": []}
        else:
            http.payload = {"data": [None, 123]}
        assert runtime.list_models(refresh=True)[0]["id"] == "a"
        assert runtime.models_error
        http.status, http.payload = 200, {"data": [{"id": "b"}]}
        assert runtime.list_models(refresh=True) == ({"id": "b"},)
        assert runtime.models_error is None


def test_successful_empty_catalog_replaces_old_models():
    with router_http() as http:
        runtime = supervisor(http.port)
        runtime.list_models(refresh=True)
        http.payload = {"data": []}
        assert runtime.list_models(refresh=True) == ()
        assert runtime.models_error is None


def worker_for(http):
    module = load_addon_module("worker.executors.llama", namespace="llama_http_flows")
    worker = module.LlamaWorkerExecutor(host="127.0.0.1", port=http.port, supervisor=SimpleNamespace())
    worker.get_status = lambda: {"is_running": True, "is_adopted": False, "generation": 1, "pid": 99}
    return worker


def test_preparation_loads_exact_id_and_observes_http_loaded_status():
    with router_http() as http:
        worker = worker_for(http)
        assert worker.prepare_model("exact-model", timeout_seconds=2)["state"] == "loaded"
        assert ("POST", "/models/load", {"model": "exact-model"}) in http.requests


def test_prepare_already_loaded_model_does_not_reload_or_unload():
    with router_http() as http:
        http.payload = {"data": [{"id": "a", "status": {"value": "loaded"}}]}
        assert worker_for(http).prepare_model("a", timeout_seconds=2)["state"] == "loaded"
        for thread in threading.enumerate():
            if thread.name == "llama-prepare-request":
                thread.join(5)
        assert all(method == "GET" for method, _, _ in http.requests)


@pytest.mark.parametrize("status", [None, "unknown", 1])
def test_prepare_tolerates_unknown_initial_status_until_loaded(status):
    with router_http() as http:
        http.payload = {"data": [{"id": "a", "status": status}]}
        assert worker_for(http).prepare_model("a", timeout_seconds=2)["state"] == "loaded"
