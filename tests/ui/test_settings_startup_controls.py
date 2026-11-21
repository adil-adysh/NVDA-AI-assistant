"""Real wx controls preserve and collect managed-provider startup policies."""
import pytest
import wx

from tests.support.settings_ui import load_settings_ui
from types import SimpleNamespace


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


def test_page_change_does_not_queue_focus_or_override_validation(settings_ui, monkeypatch):
	module, _frame = settings_ui
	queued = []
	skipped = []
	monkeypatch.setattr(wx, "CallAfter", lambda *args: queued.append(args))
	dialog = SimpleNamespace(tabs=[object()], _focus_current_page=lambda: None)
	event = SimpleNamespace(Skip=lambda: skipped.append(True))
	module.AIAssistantSettingsDialog._on_page_changed(dialog, event)
	assert skipped == [True]
	assert queued == []


def test_tool_call_limit_is_an_accessible_unsaved_draft(settings_ui, monkeypatch):
	module, frame = settings_ui
	monkeypatch.setattr(module, "get_max_tool_calls", lambda: 250)
	panel = module.AIAssistantBehaviorOutputPanel(frame, dialog=None)
	assert panel.max_tool_calls.GetValue() == "250"
	assert "Maximum tool calls" in panel.max_tool_calls.GetName()
	assert "individual" in panel.max_tool_calls.GetName()
	assert "next response" in panel.max_tool_calls.GetToolTip().GetTip()
	panel.max_tool_calls.SetValue("600")
	values = {}
	panel.collect(values)
	assert values["max_tool_calls"] == 600
	assert module.get_max_tool_calls() == 250
	for invalid in ("0", "1001", "1.5", ""):
		panel.max_tool_calls.SetValue(invalid)
		with pytest.raises(module._InvalidSetting) as error:
			panel.collect({})
		assert error.value.control is panel.max_tool_calls


def test_general_timeout_collects_an_unsaved_draft_and_validates(settings_ui, monkeypatch):
	module, frame = settings_ui
	monkeypatch.setattr(module, "get_timeout_seconds", lambda: 450)
	monkeypatch.setattr(module, "get_provider", lambda: "ollama")
	monkeypatch.setattr(module, "get_enabled_providers", lambda: ("ollama",))
	monkeypatch.setattr(module.AIAssistantGeneralPanel, "_update_active_state", lambda *_: None)
	monkeypatch.setattr(module, "build_model_manager", lambda *_args, **_kwargs: None)
	panel = module.AIAssistantGeneralPanel(frame, dialog=None)
	panel.model_combo.SetValue("draft-model")
	assert panel.timeout.GetValue() == "450"
	assert "Request timeout" in panel.timeout.GetName()
	panel.timeout.SetValue("90")
	values = {}
	panel.collect(values)
	assert values["timeout_seconds"] == 90
	assert module.get_timeout_seconds() == 450
	panel.timeout.SetValue("0")
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


def test_diagnostics_panel_explains_local_opt_in_logging_and_collects_path(settings_ui, monkeypatch, tmp_path):
	module, frame = settings_ui
	log_path = tmp_path / "assistant-diagnostics.jsonl"
	monkeypatch.setattr(module, "get_request_metrics_logging_enabled", lambda: False)
	monkeypatch.setattr(module, "get_request_metrics_log_path", lambda: str(log_path))
	panel = module.AIAssistantDiagnosticsPanel(frame, dialog=None)
	assert not panel.metrics_enabled.GetValue()
	assert "request" in panel.metrics_enabled.GetLabel().lower()
	assert "task" in panel.metrics_enabled.GetLabel().lower()
	assert "prompts" in panel.metrics_description.GetLabel().lower()
	assert "never" in panel.metrics_description.GetLabel().lower()
	assert "configured file" in panel.metrics_description.GetLabel().lower()
	assert "not uploaded" in panel.metrics_description.GetLabel().lower()
	assert "JSONL" in panel.metrics_path.GetName()
	panel.metrics_enabled.SetValue(True)
	values = {}
	panel.collect(values)
	assert values == {"metrics_enabled": True, "metrics_path": str(log_path)}


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
