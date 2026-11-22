import threading

import pytest

from tests.support import load_addon_module


def registry():
    module = load_addon_module("service.llama_operations", namespace="persistent_llama_ops")
    return module.ModelOperations()


@pytest.mark.parametrize("kind", ["load", "remove"])
def test_operation_survives_observer_detachment_and_retains_result(kind):
    ops = registry()
    entered, release = threading.Event(), threading.Event()
    seen = []
    def work(model_id, progress, cancel):
        entered.set()
        progress("Loading")
        assert release.wait(3)
    ops.bind(load=work, unload=work, remove=work)
    unsubscribe = ops.subscribe(lambda item: seen.append(item))
    operation = ops.start("a", kind)
    assert entered.wait(3)
    unsubscribe()
    try:
        assert ops.start("a", kind).operation_id == operation.operation_id
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

def test_removal_admission_cancels_and_drains_other_models_before_commit():
    ops = registry()
    entered, release, removed = threading.Event(), threading.Event(), threading.Event()
    def load(model_id, progress, cancel):
        entered.set()
        assert cancel.wait(3)
        assert release.wait(3)
    ops.bind(load=load, unload=load, remove=lambda *args: removed.set())
    first = ops.start("a", "load")
    assert entered.wait(3)
    removal = ops.start("b", "remove")
    try:
        with pytest.raises(ValueError):
            ops.start("c", "load")
        assert not removed.is_set()
        release.set()
        ops.wait(first.operation_id, timeout=3)
        ops.wait(removal.operation_id, timeout=3)
        assert removed.is_set()
        assert {x.kind: x.state for x in ops.snapshots()} == {"load": "stopped", "remove": "succeeded"}
    finally:
        release.set()
        ops.shutdown()


def test_cancelled_queued_operation_never_invokes_handler():
    ops = registry()
    entered, release = threading.Event(), threading.Event()
    called = []
    def load(model_id, progress, cancel):
        called.append(model_id)
        if model_id == "a":
            entered.set()
            assert release.wait(3)
    ops.bind(load=load, unload=load)
    first = ops.start("a", "load")
    assert entered.wait(3)
    second = ops.start("b", "load")
    ops.cancel(second.operation_id)
    release.set()
    ops.wait(first.operation_id, timeout=3)
    ops.wait(second.operation_id, timeout=3)
    assert called == ["a"]
    ops.shutdown()

def test_catalog_mutation_admission_never_waits_for_runtime_work():
    ops = registry()
    entered, release = threading.Event(), threading.Event()
    def load(*args):
        entered.set()
        assert release.wait(3)
    ops.bind(load=load, unload=load)
    operation = ops.start("a", "load")
    assert entered.wait(3)
    try:
        with pytest.raises(ValueError, match="running"):
            with ops.execution("mutation"):
                raise AssertionError("mutation was admitted")
    finally:
        release.set()
        ops.wait(operation.operation_id, timeout=3)
        ops.shutdown()
