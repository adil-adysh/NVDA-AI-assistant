import pytest

from tests.support import load_addon_module
from tests.support.settings_ui import load_settings_ui


@pytest.fixture
def dialog_module(monkeypatch):
    load_settings_ui(monkeypatch)
    return load_addon_module("ui.llama_runtime_dialog", namespace="llama_runtime_ui")


def test_ui_switches_placement_without_conflicting_options(dialog_module):
    updated = dialog_module.compose_options({"cpu-moe": "true", "no-kv-offload": "true", "chat-template": "chatml"}, {}, 1, 2, "8")
    assert updated == {"n-cpu-moe": "8", "kv-offload": "true", "chat-template": "chatml"}


def test_ui_reset_to_default_removes_managed_flags(dialog_module):
    assert dialog_module.compose_options({"cache-type-k": "q8_0", "n-cpu-moe": "4"}, {}, 0, 0, "") == {}


def test_ui_validation_rejects_empty_layer_count(dialog_module):
    with pytest.raises(ValueError, match="n-cpu-moe"):
        dialog_module.compose_options({}, {}, 0, 2, "")
