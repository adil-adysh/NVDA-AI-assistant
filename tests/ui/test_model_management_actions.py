import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.support import load_addon_module
from tests.support.settings_ui import load_settings_ui


@pytest.fixture
def module(monkeypatch):
    load_settings_ui(monkeypatch)
    speech_port = ModuleType("deterministic_model_ui.ui.nvda_ui")
    speech_port.queue = Mock()
    speech_port.message = Mock()
    monkeypatch.setitem(sys.modules, speech_port.__name__, speech_port)
    return load_addon_module("ui.model_manager", namespace="deterministic_model_ui")


def dialog_shell(module, model=None):
    state = SimpleNamespace(_is_destroyed=False, _mutation_task=None, _fetch_task=None,
        _refresh_generation=2, _refresh_pending=False, _mutation_focus=None,
        _provider=SimpleNamespace(features=SimpleNamespace(download=False, delete=True, import_model=True, import_preset=True)),
        _get_selected_model=lambda: model, _pending_downloads=set(), _models=[],
        _list=Mock(), _populate_model_list=Mock())
    for name in ("_download_btn", "_delete_btn", "_cache_delete_btn", "_import_file_btn",
                 "_import_hf_btn", "_import_preset_btn", "_set_active_btn", "_configure_btn", "_runtime_btn"):
        setattr(state, name, Mock())
    return state


def test_empty_catalog_keeps_import_buttons_enabled(module):
    dialog = dialog_shell(module)
    module.ModelManagerDialog._update_buttons(dialog)
    dialog._import_file_btn.Enable.assert_called_with(True)
    dialog._import_preset_btn.Enable.assert_called_with(True)


def test_missing_registered_source_is_removable(module):
    model = module.ManagedModel(id="missing", display_name="missing", state=module.ModelState.NOT_DOWNLOADED,
        registered=True, actions=(module.ModelAction.REMOVE,))
    dialog = dialog_shell(module, model)
    module.ModelManagerDialog._update_buttons(dialog)
    dialog._delete_btn.Enable.assert_called_with(True)
    dialog._download_btn.Enable.assert_called_with(False)
    dialog._cache_delete_btn.Enable.assert_called_with(False)


def test_old_refresh_completion_cannot_replace_post_mutation_rows(module):
    dialog = dialog_shell(module)
    module.ModelManagerDialog._on_models_fetched(dialog, ["stale"], generation=1)
    dialog._populate_model_list.assert_not_called()


def test_set_active_dispatches_off_event_thread(module):
    dialog = dialog_shell(module, module.ManagedModel("model", "model", module.ModelState.REGISTERED))
    dialog._provider.set_active_model = Mock()
    dialog._run_mutation = Mock()
    module.ModelManagerDialog._on_set_active(dialog, None)
    dialog._provider.set_active_model.assert_not_called()
    dialog._run_mutation.assert_called_once()


def test_explicit_model_ids_do_not_share_loose_active_markers(module):
    model = module.ManagedModel("model-a", "model-a", module.ModelState.REGISTERED,
        actions=(module.ModelAction.SELECT,))
    assert not module._model_matches_active(model, "modela")
