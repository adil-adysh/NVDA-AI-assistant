import pytest
from types import SimpleNamespace
from unittest.mock import Mock
import wx
from tests.support import load_addon_module
from tests.support.settings_ui import load_settings_ui


@pytest.fixture
def ui(monkeypatch):
    load_settings_ui(monkeypatch)
    return load_addon_module("ui.llama_model_manager", namespace="llama_views")


def test_view_filter_and_search_do_not_mix_assets_with_configurations(ui):
    records = load_addon_module("providers.runtime.llama_models", namespace="llama_views")
    policy = load_addon_module("providers.llama_catalog", namespace="llama_views")
    entries = policy.reconcile_llama_entries([records.LlamaModelRecord("a", "owner/a", "hugging_face", display_name="Everyday")],
                                              [], [{"id": "server"}], endpoint_owned=False)
    assert [entry.model.id for entry in ui.filter_entries(entries, "configuration", "every")] == ["a"]
    assert [entry.model.id for entry in ui.filter_entries(entries, "server", "")] == ["server"]


def test_primary_action_is_create_for_assets_use_for_configurations(ui):
    assets = load_addon_module("core.model_assets", namespace="llama_views")
    policy = load_addon_module("providers.llama_catalog", namespace="llama_views")
    rows = policy.reconcile_llama_entries([], [assets.ModelAssetSnapshot("asset", "token", "model.gguf", "llama_cache", "present", 24)], [], endpoint_owned=True)
    assert ui.primary_action(rows[0]) == "create"


def shell(ui):
    state = SimpleNamespace(_closed=False, _task=None, _generation=0, _completed_generation=-1,
        _provider=SimpleNamespace(provider_id="llama-cpp-server"), _mutation=False,
        _status=Mock(), _speak=Mock(), _update_buttons=Mock(), refresh=Mock())
    return state


def test_read_completion_does_not_refresh_or_move_focus(ui, monkeypatch):
    state = shell(ui)
    queued = []
    monkeypatch.setattr(wx, "CallAfter", lambda callback: queued.append(callback))
    submit = Mock(return_value=SimpleNamespace(cancel=Mock()))
    monkeypatch.setattr(ui.background_tasks, "submit", submit)
    received = []
    ui.LlamaModelsDialog._submit(state, lambda cancel: 42, success=received.append)
    submit.call_args.kwargs["on_success"](42)
    submit.call_args.kwargs["on_finally"]()
    for callback in queued:
        callback()
    state.refresh.assert_not_called()
    state._speak.assert_not_called()
    assert received == [42]


def test_closed_dialog_discards_late_result(ui, monkeypatch):
    state = shell(ui)
    submit = Mock(return_value=SimpleNamespace(cancel=Mock()))
    monkeypatch.setattr(ui.background_tasks, "submit", submit)
    received = Mock()
    ui.LlamaModelsDialog._submit(state, lambda cancel: 42, success=received)
    state._closed = True
    submit.call_args.kwargs["on_success"](42)
    received.assert_not_called()


def test_cancelled_read_announces_stopped_without_failure(ui, monkeypatch):
    state = shell(ui)
    submit = Mock(return_value=SimpleNamespace(cancel=Mock()))
    monkeypatch.setattr(ui.background_tasks, "submit", submit)
    ui.LlamaModelsDialog._submit(state, lambda cancel: 42)
    submit.call_args.kwargs["on_finally"]()
    state._speak.assert_called_once_with("Operation stopped.")


def test_deferred_completion_is_fenced_after_new_read_starts(ui, monkeypatch):
    state = shell(ui)
    queued = []
    monkeypatch.setattr(wx, "CallAfter", lambda callback: queued.append(callback))
    submit = Mock(return_value=SimpleNamespace(cancel=Mock()))
    monkeypatch.setattr(ui.background_tasks, "submit", submit)
    received = Mock()
    ui.LlamaModelsDialog._submit(state, lambda cancel: 1, success=received)
    submit.call_args.kwargs["on_success"](1)
    submit.call_args.kwargs["on_finally"]()
    ui.LlamaModelsDialog._submit(state, lambda cancel: 2)
    for callback in queued:
        callback()
    received.assert_not_called()

def test_unified_list_excludes_downloads_but_includes_external(ui):
    records = load_addon_module('providers.runtime.llama_models', namespace='llama_views')
    policy = load_addon_module('providers.llama_catalog', namespace='llama_views')
    entries = policy.reconcile_llama_entries([records.LlamaModelRecord('a', 'owner/a', 'hugging_face')], [], [{'id': 'server'}], endpoint_owned=False)
    assert [entry.model.id for entry in ui.filter_entries(entries, None, '')] == ['a', 'server']
