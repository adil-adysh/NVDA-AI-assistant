"""Actual wx controls, pinned NVDA helpers, background runner and catalog journeys.

Modal responses replace human input; speech and native server ownership are the
only process surfaces replaced. No provider/catalog/task scheduler is mocked.
"""
import time
import threading
from types import SimpleNamespace

import pytest
import wx

from tests.support import load_addon_module
from tests.support.llama_flow import gguf, llama_flow
from tests.integration.test_nvda_runtime import _standalone_process_services  # noqa: F401

pytestmark = pytest.mark.nvda_integration


def test_browsing_replacement_clears_old_cached_asset_identity(view, tmp_path, monkeypatch):
    module = load_addon_module("ui.llama_configuration_dialog", namespace="llama_journeys")
    a, b = gguf(tmp_path / "a.gguf"), gguf(tmp_path / "b.gguf")
    snapshot = view.flow.manager.discover_assets([{"path": str(tmp_path), "source": "user_folder"}])
    asset = next(item for item in snapshot.assets if item.path == str(a))
    dialog = module.LlamaConfigurationDialog(view.dialog, provider=view.flow.manager)
    dialog._asset = asset
    monkeypatch.setattr(wx.FileDialog, "ShowModal", lambda self: wx.ID_OK)
    monkeypatch.setattr(wx.FileDialog, "GetPath", lambda self: str(b))
    try:
        dialog._browse(None)
        assert dialog._source.GetValue() == str(b)
        assert dialog._asset is None
    finally:
        dialog.Destroy()


def test_edited_companion_is_not_claimed_verified_by_old_loaded_runtime(view, tmp_path):
    primary, vision = gguf(tmp_path / "primary.gguf"), gguf(tmp_path / "mmproj.gguf")
    view.flow.manager.create_configuration(str(primary), "a", "A", companions=[{"role": "vision", "kind": "local_file", "source": str(vision)}])
    view.flow.runtime.models = ({"id": "a", "status": {"value": "loaded"}},)
    view.dialog.refresh()
    settle(view.app, view.dialog)
    choose(view, "a")
    assert "Unverified until successful load" in view.dialog._details.GetValue()


def test_failed_edit_retains_inputs_for_retry(view, tmp_path, monkeypatch):
    add(view)
    module = load_addon_module("ui.llama_configuration_dialog", namespace="llama_journeys")
    values = {"source": "owner/model", "name": "New name", "id": "daily", "companions": [
        {"role": "vision", "kind": "local_file", "source": str(tmp_path / "missing.gguf")}], "select": False, "edit": False}
    def accept(dialog):
        dialog.values = values
        return wx.ID_OK
    monkeypatch.setattr(module.LlamaConfigurationDialog, "ShowModal", accept)
    monkeypatch.setattr(view.module.error_reporter, "report", lambda *args, **kwargs: None)
    view.dialog._edit_source(None)
    settle(view.app, view.dialog)
    names = []
    monkeypatch.setattr(module.LlamaConfigurationDialog, "ShowModal", lambda dialog: names.append(dialog._name.GetValue()) or wx.ID_CANCEL)
    view.dialog._edit_source(None)
    assert names == ["New name"]


def settle(app, dialog):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        app.ProcessPendingEvents()
        if dialog._task is None:
            app.ProcessPendingEvents()
            if dialog._task is None:
                return
        time.sleep(0.005)
    pytest.fail("Dialog operation or chained refresh did not finish")


@pytest.fixture
def view(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    app = wx.GetApp() or wx.App(False)
    flow = llama_flow(tmp_path, monkeypatch)
    module = load_addon_module("ui.llama_model_manager", namespace="llama_journeys")
    runner_module = load_addon_module("ui.task_runner", namespace="llama_journeys")
    metrics = load_addon_module("observability.reporter", namespace="llama_journeys")
    monkeypatch.setattr(metrics, "get_request_metrics_logging_enabled", lambda: False)
    runner = runner_module.BackgroundTaskRunner(max_workers=1)
    monkeypatch.setattr(module, "background_tasks", runner)
    spoken = []
    monkeypatch.setattr(module.LlamaModelsDialog, "_speak", lambda self, text: spoken.append(text))
    dialog = module.LlamaModelsDialog(None, flow.manager)
    settle(app, dialog)
    try:
        yield SimpleNamespace(app=app, dialog=dialog, flow=flow, module=module, spoken=spoken)
    finally:
        dialog._closed = True
        if dialog._task:
            dialog._task.cancel()
        runner._executor.shutdown(wait=True, cancel_futures=True)
        dialog.Destroy()
        app.ProcessPendingEvents()


def choose(view, identity):
    for index, entry in enumerate(view.dialog._rows):
        if entry.model.id == identity:
            view.dialog._list.Select(index)
            view.dialog._selection_changed()
            return
    pytest.fail(f"Missing row {identity}")


def add(view, identity="daily"):
    view.flow.manager.create_configuration("owner/model", identity, "Daily")
    view.dialog.refresh()
    settle(view.app, view.dialog)
    choose(view, identity)


def test_create_and_use_then_edit_runtime_really_commits(view, monkeypatch):
    create = load_addon_module("ui.llama_configuration_dialog", namespace="llama_journeys")
    runtime = load_addon_module("ui.llama_runtime_dialog", namespace="llama_journeys")
    def accept(dialog):
        dialog.values = {"source": "owner/model:Q4_K_M", "name": "Everyday", "id": "daily", "select": True, "edit": True}
        return wx.ID_OK
    monkeypatch.setattr(create.LlamaConfigurationDialog, "ShowModal", accept)
    def settings(dialog):
        dialog._controls["ctx-size"].SetValue("4096")
        dialog._moe.SetSelection(2)
        dialog._layers.SetValue("4")
        dialog._save(None)
        return wx.ID_OK
    monkeypatch.setattr(runtime.LlamaRuntimeDialog, "ShowModal", settings)
    monkeypatch.setattr(runtime.LlamaRuntimeDialog, "EndModal", lambda *args: None)
    view.dialog._create()
    settle(view.app, view.dialog)
    assert view.flow.manager.active_model_id == "daily"
    assert view.flow.manager.get_runtime_options("daily") == {"ctx-size": "4096", "n-cpu-moe": "4"}
    assert view.dialog._selected().model.id == "daily"
    assert any("created" in text for text in view.spoken)
    assert not view.flow.runtime.starts


def test_cached_asset_add_creates_and_uses_files(view, tmp_path, monkeypatch):
    path = gguf(tmp_path / "cache/weights.gguf")
    view.flow.manager.discover_assets([{"path": str(path.parent), "source": "user_folder"}])
    asset = next(entry.asset for entry in view.flow.manager.list_model_entries() if entry.kind == "downloaded")
    create = load_addon_module("ui.llama_configuration_dialog", namespace="llama_journeys")
    def accept(dialog):
        assert not dialog._source.IsEnabled()
        assert dialog._kind.GetSelection() == 2
        dialog.values = {"source": str(path), "name": "Cached", "id": "cached", "select": True, "edit": False}
        return wx.ID_OK
    monkeypatch.setattr(create.LlamaConfigurationDialog, "ShowModal", accept)
    view.dialog._create(asset)
    settle(view.app, view.dialog)
    assert view.flow.manager.active_model_id == "cached"
    assert path.is_file() and {entry.kind for entry in view.dialog._rows} == {"configuration"}
    assert not view.flow.runtime.starts


def test_visibility_is_persisted_and_use_keeps_exact_identity(view):
    add(view)
    view.dialog._visible.SetValue(False)
    view.dialog._visibility_changed(None)
    settle(view.app, view.dialog)
    store = view.module.ModelVisibilityStore()
    assert not store.is_model_visible("llama-cpp-server", "daily")
    view.dialog._primary_action()
    settle(view.app, view.dialog)
    assert view.flow.manager.active_model_id == "daily"


def test_duplicate_dialog_creates_new_selected_row(view, monkeypatch):
    add(view)
    monkeypatch.setattr(wx.TextEntryDialog, "ShowModal", lambda self: wx.ID_OK)
    monkeypatch.setattr(wx.TextEntryDialog, "GetValue", lambda self: "Long context")
    view.dialog._duplicate(None)
    settle(view.app, view.dialog)
    assert {entry.model.id for entry in view.dialog._rows} == {"daily", "Long-context"}
    assert view.dialog._selected().model.id == "Long-context"


def test_locate_missing_file_uses_replacement_without_losing_settings(view, tmp_path, monkeypatch):
    path = gguf(tmp_path / "old.gguf")
    view.flow.manager.create_configuration(str(path), "missing", "Missing")
    view.flow.manager.set_runtime_options("missing", {"cache-type-k": "q8_0"})
    path.unlink()
    replacement = gguf(tmp_path / "new.gguf")
    view.dialog.refresh()
    settle(view.app, view.dialog)
    choose(view, "missing")
    assert view.dialog._buttons["primary"].GetLabel().startswith("Locate")
    monkeypatch.setattr(wx.FileDialog, "ShowModal", lambda self: wx.ID_OK)
    monkeypatch.setattr(wx.FileDialog, "GetPath", lambda self: str(replacement))
    view.dialog._primary_action()
    settle(view.app, view.dialog)
    assert view.flow.manager.get_available_model_ids() == ["missing"]
    assert view.flow.manager.get_runtime_options("missing") == {"cache-type-k": "q8_0"}


@pytest.mark.parametrize("confirm", [wx.YES, wx.NO])
def test_remove_confirmation_keeps_weights_and_obeys_choice(view, tmp_path, monkeypatch, confirm):
    path = gguf(tmp_path / "weights.gguf")
    view.flow.manager.create_configuration(str(path), "daily", "Daily", select=True)
    view.dialog.refresh()
    settle(view.app, view.dialog)
    choose(view, "daily")
    monkeypatch.setattr(wx, "MessageBox", lambda *args, **kwargs: confirm)
    view.dialog._remove(None)
    settle(view.app, view.dialog)
    assert bool(view.flow.manager.find_record("daily", register_missing=False)) == (confirm == wx.NO)
    assert path.is_file()


@pytest.mark.parametrize("confirm", [wx.YES, wx.NO])
def test_preset_preview_confirmation_really_controls_commit(view, tmp_path, monkeypatch, confirm):
    source = tmp_path / "import.ini"
    source.write_text("version = 1\n[imported]\nhf-repo = owner/model\n", encoding="utf-8")
    before = source.read_bytes()
    monkeypatch.setattr(wx.FileDialog, "ShowModal", lambda self: wx.ID_OK)
    monkeypatch.setattr(wx.FileDialog, "GetPath", lambda self: str(source))
    monkeypatch.setattr(wx, "MessageBox", lambda *args, **kwargs: confirm)
    view.dialog._import_preset(None)
    settle(view.app, view.dialog)
    assert bool(view.flow.manager.find_record("imported", register_missing=False)) == (confirm == wx.YES)
    assert source.read_bytes() == before


def test_refresh_retains_search_focus_selection_and_stale_rows(view):
    view.flow.runtime.models = ({"id": "external"},)
    view.dialog.refresh()
    settle(view.app, view.dialog)
    choose(view, "external")
    view.dialog._search.SetValue("ext")
    view.flow.runtime.models_error = "temporarily offline"
    view.dialog.refresh()
    settle(view.app, view.dialog)
    assert view.dialog._search.GetValue() == "ext"
    assert view.dialog._selected().model.id == "external"
    assert not view.dialog._buttons["primary"].IsEnabled()
    assert "failed" in view.dialog._status.GetLabel()


def test_list_activation_does_not_open_create_dialog_during_operation(view, tmp_path, monkeypatch):
    add(view)
    entered, release = threading.Event(), threading.Event()
    def slow(cancel):
        entered.set()
        assert release.wait(5)
    view.dialog._submit(slow)
    assert entered.wait(5)
    create = load_addon_module("ui.llama_configuration_dialog", namespace="llama_journeys")
    opened = []
    monkeypatch.setattr(create.LlamaConfigurationDialog, "ShowModal", lambda self: opened.append(True) or wx.ID_CANCEL)
    try:
        view.dialog._primary_action()
        assert opened == []
    finally:
        release.set()
        settle(view.app, view.dialog)


def test_add_downloads_folder_lists_assets_with_provenance(view, tmp_path, monkeypatch):
    path = gguf(tmp_path / "new-cache/weights.gguf")
    create = load_addon_module("ui.llama_configuration_dialog", namespace="llama_journeys")
    dialog = create.LlamaConfigurationDialog(view.dialog, provider=view.flow.manager)
    monkeypatch.setattr(wx.DirDialog, "ShowModal", lambda self: wx.ID_OK)
    monkeypatch.setattr(wx.DirDialog, "GetPath", lambda self: str(path.parent))
    try:
        dialog._choose_folder(None)
        settle(view.app, dialog)
        assert dialog._kind.GetSelection() == 2
        assert dialog._files[0].path == str(path)
        assert "user_folder" in dialog._artifacts.GetString(0)
        dialog._artifacts.SetSelection(0)
        dialog._artifact_changed(None)
        assert dialog._asset.path == str(path)
        assert dialog._name.GetValue() == "weights"
    finally:
        dialog._closed = True
        dialog.Destroy()


def test_collision_retains_draft_and_existing_configuration(view, monkeypatch):
    add(view)
    create = load_addon_module("ui.llama_configuration_dialog", namespace="llama_journeys")
    values = {"source": "owner/other", "name": "Retry name", "id": "daily", "select": True, "edit": False}
    def accept(dialog):
        dialog.values = values
        return wx.ID_OK
    monkeypatch.setattr(create.LlamaConfigurationDialog, "ShowModal", accept)
    monkeypatch.setattr(view.module.error_reporter, "report", lambda *args, **kwargs: None)
    view.dialog._create()
    settle(view.app, view.dialog)
    assert view.dialog._draft == values
    assert view.flow.manager.find_record("daily", register_missing=False).source == "owner/model"
    assert view.flow.manager.active_model_id is None
    assert "failed" in view.dialog._status.GetLabel()


def test_close_add_during_scan_discards_late_files(view, tmp_path, monkeypatch):
    path = gguf(tmp_path / "cache/weights.gguf")
    original = view.flow.assets.discover_model_assets
    entered, release = threading.Event(), threading.Event()
    def scan(roots, generation):
        entered.set()
        assert release.wait(5)
        return original(roots, generation)
    monkeypatch.setattr(view.flow.assets, "discover_model_assets", scan)
    create = load_addon_module("ui.llama_configuration_dialog", namespace="llama_journeys")
    dialog = create.LlamaConfigurationDialog(view.dialog, provider=view.flow.manager)
    dialog._roots = [{"path": str(path.parent), "source": "user_folder"}]
    dialog._kind.SetSelection(2)
    dialog._resolve_source(None)
    assert entered.wait(5)
    task = dialog._task
    monkeypatch.setattr(create.LlamaConfigurationDialog, "EndModal", lambda *args: None)
    try:
        dialog._close(None)
        assert task.cancel_event.is_set()
        release.set()
        task._future.exception(timeout=5)
        view.app.ProcessPendingEvents()
        assert dialog._files == []
    finally:
        release.set()
        dialog.Destroy()


def test_load_reports_loaded_only_after_worker_http_completion(view):
    from tests.support.llama_http import router_http
    add(view, "a")
    with router_http() as http:
        view.flow.executor.host, view.flow.executor.port = "127.0.0.1", http.port
        view.flow.executor.get_status = lambda: {"is_running": True, "is_adopted": False, "generation": 1, "pid": 99}
        view.dialog._lifecycle(None)
        view.flow.manager.model_operations.wait(view.flow.manager.model_operations.snapshots()[-1].operation_id, timeout=5)
        settle(view.app, view.dialog)
        assert ("POST", "/models/load", {"model": "a"}) in http.requests
        assert any("Model loaded" in text for text in view.spoken)


def test_escape_button_route_cancels_owned_task(view, monkeypatch):
    monkeypatch.setattr(view.module.LlamaModelsDialog, "EndModal", lambda self, code: None)
    close = next(child for child in view.dialog.GetChildren() if child.GetId() == view.dialog.GetEscapeId())
    event = wx.CommandEvent(wx.EVT_BUTTON.typeId, close.GetId())
    close.GetEventHandler().ProcessEvent(event)
    assert view.dialog._closed


def test_runtime_downgrade_reset_and_invalid_field_focus(view, monkeypatch):
    runtime = load_addon_module("ui.llama_runtime_dialog", namespace="llama_journeys")
    supported = {"ctx-size", "cache-type-k", "cpu-moe", "n-cpu-moe", "kv-offload", "no-kv-offload"}
    dialog = runtime.LlamaRuntimeDialog(view.dialog, "a", {"moe-cache-mib": "512", "chat-template": "chatml"}, supported)
    monkeypatch.setattr(runtime.LlamaRuntimeDialog, "EndModal", lambda *args: None)
    boxes = []
    monkeypatch.setattr(wx, "MessageBox", lambda message, *args, **kwargs: boxes.append(message) or wx.YES)
    try:
        dialog._save(None)
        assert dialog.options == {"moe-cache-mib": "512", "chat-template": "chatml"}
        dialog._clear_unsupported("moe-cache-mib", dialog._controls["moe-cache-mib"])
        dialog._clear_other("chat-template")
        dialog._save(None)
        assert dialog.options == {}
        dialog._moe.SetSelection(2)
        dialog._layers.Enable(True)
        dialog._layers.SetValue("bad")
        dialog._save(None)
        assert dialog._book.GetSelection() == 1
        assert boxes and "n-cpu-moe" in boxes[-1]
        dialog._layers.SetValue("4")
        dialog._save(None)
        assert dialog.options == {"n-cpu-moe": "4"}
        dialog._reset(None)
        dialog._save(None)
        assert dialog.options == {}
    finally:
        dialog.Destroy()

def test_close_detaches_without_cancelling_application_operation(view, monkeypatch):
    add(view)
    entered, release = threading.Event(), threading.Event()
    registry = view.flow.manager.model_operations
    def load(model_id, progress, cancel):
        entered.set()
        assert release.wait(5)
        assert not cancel.is_set()
        progress('Finished background load')
    registry.bind(load=load, unload=view.flow.manager.unload_model)
    operation = registry.start('daily', 'load')
    assert entered.wait(5)
    monkeypatch.setattr(view.module.LlamaModelsDialog, 'EndModal', lambda *args: None)
    try:
        view.dialog._close(None)
        assert registry.active('daily')
        release.set()
        registry.wait(operation.operation_id, timeout=5)
        assert registry.snapshots()[-1].state == 'succeeded'
        reopened = view.module.LlamaModelsDialog(None, view.flow.manager)
        try:
            settle(view.app, reopened)
            assert reopened._provider.model_operations.snapshots()[-1].operation_id == operation.operation_id
            assert reopened._buttons['tasks'].IsEnabled()
            assert not hasattr(reopened, '_view')
        finally:
            reopened._unsubscribe()
            reopened._closed = True
            reopened.Destroy()
    finally:
        release.set()
