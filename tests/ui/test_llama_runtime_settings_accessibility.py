import pytest
from tests.support import load_addon_module
from tests.support.settings_ui import load_settings_ui


def test_unavailable_imported_values_are_retained_until_explicit_reset(monkeypatch):
    load_settings_ui(monkeypatch)
    dialog = load_addon_module("ui.llama_runtime_dialog", namespace="runtime_accessible")
    values = dialog.runtime_field_state({"moe-cache-mib": "512"}, {"ctx-size"}, provider_context=8192)
    assert values["moe-cache-mib"]["stored"] == "512"
    assert values["moe-cache-mib"]["supported"] is False
    assert values["ctx-size"]["effective"] == "8192"
    assert values["ctx-size"]["origin"] == "provider"


def test_invalid_value_identifies_field_for_focus(monkeypatch):
    load_settings_ui(monkeypatch)
    dialog = load_addon_module("ui.llama_runtime_dialog", namespace="runtime_accessible")
    with pytest.raises(ValueError, match="n-cpu-moe"):
        dialog.compose_options({}, {}, 0, 2, "-2")
