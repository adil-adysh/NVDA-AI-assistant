from unittest.mock import Mock
import threading

import pytest
from tests.support import load_addon_module


def executor():
    worker = load_addon_module("worker.executors.llama", namespace="prepare_ux")
    status = {"is_running": True, "is_adopted": False, "generation": 1, "pid": 1}
    instance = worker.LlamaWorkerExecutor(supervisor=Mock())
    instance.get_status = Mock(return_value=status)
    return worker, instance


def test_preparation_waits_for_loaded_status(monkeypatch):
    worker, instance = executor()
    monkeypatch.setattr(instance, "_model_request", Mock(return_value={}))
    instance.list_models = Mock(side_effect=[[{"id": "a", "status": {"value": "loading"}}], [{"id": "a", "status": {"value": "loaded"}}]])
    assert instance.prepare_model("a", timeout_seconds=2)["state"] == "loaded"


def test_preparation_does_not_mutate_external_server(monkeypatch):
    worker, instance = executor()
    instance.get_status.return_value = {"is_running": True, "is_adopted": True}
    with pytest.raises(ValueError, match="owned"):
        instance.prepare_model("a")


def test_preparation_reports_failed_load(monkeypatch):
    worker, instance = executor()
    monkeypatch.setattr(instance, "_model_request", Mock(return_value={}))
    instance.list_models = Mock(return_value=[{"id": "a", "status": {"value": "unloaded", "failed": True}}])
    with pytest.raises(ValueError, match="failed"):
        instance.prepare_model("a", timeout_seconds=2)


def test_cancelled_load_completion_cannot_unload_successful_retry(monkeypatch):
    worker, instance = executor()
    pending, release, returned = threading.Event(), threading.Event(), threading.Event()
    requests = []
    def request(operation, model_id, timeout):
        requests.append(operation)
        if operation == "load" and requests.count("load") == 1:
            pending.set()
            assert release.wait(5)
            returned.set()
        return {}
    instance._model_request = request
    checks = iter([None, RuntimeError("cancelled")])
    def check():
        error = next(checks)
        if error:
            assert pending.wait(5)
            raise error
    monkeypatch.setattr(worker, "check_job_cancelled", check)
    with pytest.raises(RuntimeError, match="cancelled"):
        instance.prepare_model("a")
    monkeypatch.setattr(worker, "check_job_cancelled", lambda: None)
    instance.list_models = Mock(return_value=[{"id": "a", "status": {"value": "loaded"}}])
    assert instance.prepare_model("a")["state"] == "loaded"
    before = requests.count("unload")
    release.set()
    assert returned.wait(5)
    # Join the old loader so its finally/cleanup has actually executed.
    for thread in threading.enumerate():
        if thread.name == "llama-prepare-request":
            thread.join(5)
    assert requests.count("unload") == before


def test_failed_cleanup_status_does_not_replace_original_prepare_error(monkeypatch):
    worker, instance = executor()
    healthy = instance.get_status.return_value
    instance.get_status.side_effect = [healthy, RuntimeError("status unavailable")]
    instance.list_models = Mock(return_value=[])
    instance._model_request = Mock(side_effect=ValueError("original load failure"))
    with pytest.raises(ValueError, match="original load failure"):
        instance.prepare_model("a", timeout_seconds=2)
