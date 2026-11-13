import threading

import pytest

from tests.support import load_addon_module


def registry():
    module = load_addon_module("service.llama_operations", namespace="persistent_llama_ops")
    return module.ModelOperations()


def test_operation_survives_observer_detachment_and_retains_result():
    ops = registry()
    entered, release = threading.Event(), threading.Event()
    seen = []
    def work(model_id, progress, cancel):
        entered.set()
        progress("Loading")
        assert release.wait(3)
    ops.bind(load=work, unload=work)
    unsubscribe = ops.subscribe(lambda item: seen.append(item))
    operation = ops.start("a", "load")
    assert entered.wait(3)
    unsubscribe()
    try:
        assert ops.start("a", "load").operation_id == operation.operation_id
        with pytest.raises(ValueError):
            ops.start("a", "unload")
        release.set()
        ops.wait(operation.operation_id, timeout=3)
        assert ops.snapshots()[-1].state == "succeeded"
        assert "Loading" in ops.snapshots()[-1].history
    finally:
        release.set()
        ops.shutdown()


def test_stop_targets_one_operation_and_preserves_another():
    ops = registry()
    entered = threading.Event()
    def work(model_id, progress, cancel):
        if model_id == "a":
            entered.set()
            assert cancel.wait(3)
    ops.bind(load=work, unload=work)
    first = ops.start("a", "load")
    assert entered.wait(3)
    second = ops.start("b", "load")
    ops.cancel(first.operation_id)
    ops.wait(first.operation_id, timeout=3)
    ops.wait(second.operation_id, timeout=3)
    assert {item.model_id: item.state for item in ops.snapshots()} == {"a": "stopped", "b": "succeeded"}
    ops.shutdown()


def test_failure_is_retained_and_shutdown_rejects_new_jobs():
    ops = registry()
    def fail(*args):
        raise ValueError("bad configuration token=secret")
    ops.bind(load=fail, unload=fail)
    operation = ops.start("a", "load")
    ops.wait(operation.operation_id, timeout=3)
    result = ops.snapshots()[0]
    assert result.state == "failed" and "bad configuration" in result.error
    assert "secret" not in result.error
    ops.shutdown()
    with pytest.raises(RuntimeError):
        ops.start("a", "load")
