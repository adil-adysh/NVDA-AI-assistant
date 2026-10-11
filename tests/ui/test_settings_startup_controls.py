"""Real wx controls preserve and collect managed-provider startup policies."""
import pytest
import wx

from tests.support.settings_ui import load_settings_ui


@pytest.fixture
def settings_ui(monkeypatch):
	app = wx.App.Get() or wx.App(False)
	frame = wx.Frame(None)
	frame.Hide()
	module = load_settings_ui(monkeypatch)
	try:
		yield module, frame
	finally:
		frame.Destroy()
		app.ProcessPendingEvents()


def test_startup_choices_collect_separate_policies_and_expose_help(settings_ui, monkeypatch):
	module, frame = settings_ui
	monkeypatch.setattr(module, "get_local_startup_mode", lambda provider: "worker" if provider == "litert-lm" else "server")
	panel = module.AIAssistantRuntimePanel(frame, dialog=None)
	assert panel.litert_startup.GetSelection() == 1
	assert panel.llama_startup.GetSelection() == 2
	assert panel.litert_startup.GetName().startswith("LiteRT-LM startup.")
	assert "first inference" in panel.litert_startup.GetName()
	assert panel.litert_startup.GetToolTip().GetTip()
	panel.llama_startup.SetSelection(0)
	values = {}
	panel.collect(values)
	assert values["litert_startup"] == "worker"
	assert values["llama_startup"] == "lazy"
	panel.litert_startup.SetSelection(wx.NOT_FOUND)
	with pytest.raises(module._InvalidSetting):
		panel.collect({})


def test_chat_settings_collect_without_saving(settings_ui, monkeypatch):
	module, frame = settings_ui
	monkeypatch.setattr(module, 'get_chat_auto_read', lambda: False)
	monkeypatch.setattr(module, 'get_chat_status_announcements', lambda: True)
	panel = module.AIAssistantBehaviorOutputPanel(frame, dialog=None)
	assert not panel.chat_auto_read.GetValue()
	assert panel.chat_status_announcements.GetValue()
	panel.chat_auto_read.SetValue(True)
	panel.chat_status_announcements.SetValue(False)
	values = {}
	panel.collect(values)
	assert values['chat_auto_read'] is True
	assert values['chat_status_announcements'] is False
	assert module.get_chat_auto_read() is False


@pytest.mark.parametrize('mode', ['speak_then_display', 'display_only', 'speak_only'])
def test_output_choice_loads_and_collects_without_changing_configuration(settings_ui, monkeypatch, mode):
	module, frame = settings_ui
	monkeypatch.setattr(module, 'get_one_shot_output_mode', lambda: mode)
	panel = module.AIAssistantBehaviorOutputPanel(frame, dialog=None)
	assert panel.one_shot_output.GetSelection() == module.ONE_SHOT_OUTPUT_MODES.index(mode)
	assert 'not chat' in panel.one_shot_output.GetName()
	panel.one_shot_output.SetSelection(1)
	values = {}
	panel.collect(values)
	assert values['one_shot_output_mode'] == 'display_only'
	assert module.get_one_shot_output_mode() == mode
	panel.one_shot_output.SetSelection(wx.NOT_FOUND)
	with pytest.raises(module._InvalidSetting):
		panel.collect({})
