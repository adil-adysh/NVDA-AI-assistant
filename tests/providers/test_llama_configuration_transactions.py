import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from tests.support import load_addon_module


def manager(tmp_path):
    mod = load_addon_module("providers.llama_manager", namespace="transactions_ux")
    return mod.LlamaCppModelManager(cache_dir=tmp_path / "managed", supervisor=Mock())


def test_named_preset_is_committed_in_one_catalog_write(tmp_path, monkeypatch):
    m = manager(tmp_path)
    write = Mock(wraps=m._catalog.upsert)
    monkeypatch.setattr(m._catalog, "upsert", write)
    m.create_preset("owner/model", "daily", "Everyday")
    assert write.call_count == 1
    assert write.call_args.args[0].display_name == "Everyday"


def test_preset_creation_never_reads_a_preset_file(tmp_path):
    source = tmp_path / "preset.ini"
    source.write_text("version = 1\n[ignored]\nhf-repo = owner/ignored\n", encoding="utf-8")
    m = manager(tmp_path)
    m.create_preset("owner/model", "daily", "Everyday")
    assert [record.model_id for record in m.list_presets()] == ["daily"]
    assert not hasattr(m, "import_preset")


def test_duplicate_preset_id_is_rejected_without_writes(tmp_path):
    m = manager(tmp_path)
    m.create_preset("owner/model", "daily", "Everyday")
    before = (tmp_path / "managed/models.json").read_bytes()
    try:
        m.create_preset("owner/other", "daily", "Duplicate")
    except ValueError as error:
        assert "already exists" in str(error)
    else:
        raise AssertionError("duplicate ID was accepted")
    assert (tmp_path / "managed/models.json").read_bytes() == before

@pytest.mark.parametrize("adopted", [False, True])
def test_removal_fences_restart_between_stop_and_catalog_commit(tmp_path, monkeypatch, adopted):
    m = manager(tmp_path)
    m.create_preset("owner/model", "a", "A")
    record = m.find_record("a")
    entered, release = threading.Event(), threading.Event()
    m._supervisor.status.return_value.is_running = True
    m._supervisor.status.return_value.is_adopted = adopted
    original = m._catalog.remove
    def remove(model_id):
        entered.set()
        assert release.wait(3)
        original(model_id)
    monkeypatch.setattr(m._catalog, "remove", remove)
    restart = Mock()
    monkeypatch.setattr(m, "_ensure_running", restart)
    with ThreadPoolExecutor() as pool:
        deletion = pool.submit(m.delete_model, "a")
        try:
            assert entered.wait(3)
            with pytest.raises(ValueError, match="remov"):
                m.ensure_running(record)
            restart.assert_not_called()
        finally:
            release.set()
        deletion.result(3)
    assert m.find_record("a") is None
    assert m._supervisor.stop.call_count == (0 if adopted else 1)


def test_removal_failure_restores_selection_and_releases_native_fence(tmp_path, monkeypatch):
    from types import SimpleNamespace
    m = manager(tmp_path)
    m._config = SimpleNamespace(model_name="a")
    m.create_preset("owner/model", "a", "A")
    m._supervisor.status.return_value.is_running = False
    m._supervisor.pause_startup.return_value = 12
    monkeypatch.setattr(m._catalog, "remove", Mock(side_effect=OSError("disk failed")))
    with pytest.raises(OSError, match="disk failed"):
        m.delete_model("a")
    assert m.active_model_id == "a"
    assert m.find_record("a") is not None
    m._supervisor.resume_startup.assert_called_once_with(12)
    m.create_preset("owner/other", "b", "B")


def test_stop_during_native_fence_ack_releases_fence_and_keeps_preset(tmp_path):
    m = manager(tmp_path)
    m.create_preset("owner/model", "a", "A")
    entered, release = threading.Event(), threading.Event()
    def pause():
        entered.set()
        assert release.wait(3)
        return 19
    m._supervisor.pause_startup.side_effect = pause
    operations = m.model_operations
    removal = operations.start("a", "remove")
    assert entered.wait(3)
    operations.cancel(removal.operation_id)
    release.set()
    operations.wait(removal.operation_id, timeout=3)
    assert next(x for x in operations.snapshots() if x.operation_id == removal.operation_id).state == "stopped"
    m._supervisor.resume_startup.assert_called_once_with(19)
    m._supervisor.stop.assert_not_called()
    assert m.find_record("a") is not None

@pytest.mark.parametrize("state", ["starting", "restarting"])
def test_removal_drains_owned_startup_even_before_pid_is_published(tmp_path, state):
    from types import SimpleNamespace
    m = manager(tmp_path)
    m.create_preset("owner/model", "a", "A")
    m._supervisor.status.return_value = SimpleNamespace(state=state, is_running=False, is_adopted=False)
    m.delete_model("a")
    m._supervisor.stop.assert_called_once_with(strict=True)


def test_removed_record_cannot_restart_router_after_removal_finishes(tmp_path, monkeypatch):
    m = manager(tmp_path)
    m.create_preset("owner/model", "a", "A")
    stale = m.find_record("a")
    m._supervisor.status.return_value.is_running = False
    m.delete_model("a")
    launch = Mock()
    monkeypatch.setattr(m, "_ensure_running", launch)
    with pytest.raises(ValueError, match="no longer registered"):
        m.ensure_running(stale)
    launch.assert_not_called()


def test_edited_record_cannot_start_stale_configuration(tmp_path, monkeypatch):
    m = manager(tmp_path)
    m.create_preset("owner/model", "a", "A")
    stale = m.find_record("a")
    m.update_preset("a", options={"ctx-size": "4096"})
    launch = Mock()
    monkeypatch.setattr(m, "_ensure_running", launch)
    with pytest.raises(ValueError, match="changed"):
        m.ensure_running(stale)
    launch.assert_not_called()
