"""Hidden wx dialogs using the pinned NVDA GUI helpers, not widget stubs."""
from types import SimpleNamespace

import pytest
import wx

from tests.support import load_addon_module
from tests.integration.test_nvda_runtime import _standalone_process_services  # noqa: F401

pytestmark = pytest.mark.nvda_integration


def test_llama_dialogs_construct_with_real_nvda_helpers(monkeypatch):
    app = wx.GetApp() or wx.App(False)
    manager = load_addon_module("ui.llama_model_manager", namespace="real_llama_dialogs")
    preset = load_addon_module("ui.llama_preset_dialog", namespace="real_llama_dialogs")
    generation = load_addon_module("ui.model_config_dialog", namespace="real_llama_dialogs")
    monkeypatch.setattr(generation, "_base_sampling", lambda provider: generation.ModelSamplingConfig())
    monkeypatch.setattr(generation, "get_model_sampling", lambda *args: generation.ModelSamplingConfig())
    monkeypatch.setattr(manager.LlamaModelsDialog, "_refresh", lambda self: None)
    operations = load_addon_module("service.llama_operations", namespace="real_llama_dialogs").ModelOperations()
    monkeypatch.setattr(preset.LlamaPresetDialog, "_scan_cache", lambda self: None)
    dialogs = []
    provider = SimpleNamespace(provider_id="llama-cpp-server", active_model_id=None, model_operations=operations)
    try:
        parent = manager.LlamaModelsDialog(None, provider)
        dialogs.append(parent)
        assert [parent._list.GetColumn(i).GetText() for i in range(parent._list.GetColumnCount())] == [
            "Name", "Source", "Mode", "Draft", "Selected", "Runtime",
        ]
        assert parent.GetEscapeId() == wx.ID_CANCEL
        create = preset.LlamaPresetDialog(parent, provider)
        dialogs.append(create)
        assert create.GetEscapeId() == wx.ID_CANCEL
        assert create._tabs.GetPageCount() == 3
        sampling = generation.ModelConfigureDialog(parent, "llama-cpp-server", "model", "Everyday",
            field_labels={"num_ctx": "Request context budget (tokens):"}, extra_fields=(generation.MODEL_FIELD_BY_ID["seed"],))
        dialogs.append(sampling)
        assert sampling._lch["num_ctx"].control.GetName() == "Request context budget (tokens) value"
        assert "Request context budget" in sampling._use_default_cbs["num_ctx"].GetLabel()
        sampling._use_default_cbs["seed"].SetValue(False)
        sampling._lch["seed"].control.SetValue("42")
        assert sampling._draft_config().seed == 42
    finally:
        for dialog in reversed(dialogs):
            dialog.Destroy()
        app.ProcessPendingEvents()
