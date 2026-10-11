"""Catalog completion must preserve drafts and respect refresh generations."""
from types import SimpleNamespace

import pytest
import wx

from tests.support.settings_ui import load_settings_ui


@pytest.fixture
def general_panel(monkeypatch):
	app = wx.App.Get() or wx.App(False)
	frame = wx.Frame(None)
	frame.Hide()
	module = load_settings_ui(monkeypatch)
	callbacks = []
	monkeypatch.setattr(module.background_tasks, "submit", lambda work, **kwargs: callbacks.append(kwargs["on_success"]) or SimpleNamespace(done=True, cancel=lambda: None))
	monkeypatch.setattr(module.AIAssistantGeneralPanel, "_refresh_status", lambda *_args: None)
	monkeypatch.setattr(module.AIAssistantGeneralPanel, "_current_model_name", lambda self, provider: "saved-" + provider)
	panel = module.AIAssistantGeneralPanel(frame, dialog=None)
	try:
		yield module, panel, callbacks
	finally:
		frame.Destroy()
		app.ProcessPendingEvents()


def test_catalog_refresh_preserves_unsaved_model_draft(general_panel):
	_module, panel, callbacks = general_panel
	callbacks[0](["catalog-model"])
	panel.model_combo.SetValue("unsaved-model")
	panel._refresh_model_choices(panel.selected_provider())
	callbacks[-1](["refreshed-model"])
	assert panel.model_combo.GetValue() == "unsaved-model"


def test_old_catalog_completion_cannot_overwrite_a_newer_refresh(general_panel):
	_module, panel, callbacks = general_panel
	panel._refresh_model_choices(panel.selected_provider())
	callbacks[-1](["new-model"])
	callbacks[0](["old-model"])
	assert list(panel.model_combo.GetItems()) == ["new-model"]


def test_global_top_p_rejects_values_above_one(general_panel):
	module, panel, _callbacks = general_panel
	models = module.AIAssistantModelsContextPanel(panel.GetParent(), dialog=None)
	models.top_p.SetValue("1.5")
	with pytest.raises(module._InvalidSetting):
		models.collect({})
