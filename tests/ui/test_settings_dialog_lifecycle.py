"""Open/close/reopen through NVDA's pinned SettingsDialog lifecycle and real wx."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import wx

from tests.support.settings_ui import load_settings_ui


def pump_events():
	app = wx.App.Get()
	wx.CallLater(20, app.ExitMainLoop)
	app.MainLoop()


@pytest.fixture
def dialog_ui(monkeypatch):
	app = wx.App.Get() or wx.App(False)
	module = load_settings_ui(monkeypatch, real_dialog_shell=True)
	monkeypatch.setattr(module.AIAssistantGeneralPanel, "_update_active_state", lambda *_: None)
	tasks = []
	def submit(*_args, **_kwargs):
		task = SimpleNamespace(cancel=Mock())
		tasks.append(task)
		return task
	monkeypatch.setattr(module.background_tasks, "submit", submit)
	frame = wx.Frame(None)
	def popup(dialog_class, **kwargs):
		dialog_class(frame, **kwargs).Show()
	frame.popupSettingsDialog = popup
	# A modal loop must never be entered by the settings entry point.
	monkeypatch.setattr(module.AIAssistantSettingsDialog, "ShowModal", lambda *_: pytest.fail("settings entered modal loop"))
	try:
		yield module, frame, tasks
	finally:
		frame.Destroy()
		app.ProcessPendingEvents()


def test_opening_settings_reuses_live_dialog_and_reopens_after_destroy_with_retained_reference(dialog_ui):
	module, frame, tasks = dialog_ui
	first = module.open_settings_dialog(frame)
	assert first.IsShown()
	assert module.open_settings_dialog(frame) is first
	first.Destroy()
	pump_events()
	# Keep first alive deliberately: this reproduced the native log failure.
	second = module.open_settings_dialog(frame)
	assert second is not first
	assert second.IsShown()
	assert tasks == []  # Opening Settings does not need the embedding worker.
	assert first.tabs == []
	second.onCancel(wx.CommandEvent())
	pump_events()


def test_apply_keeps_dialog_open_and_cancel_does_not_persist(dialog_ui, monkeypatch):
	module, frame, _tasks = dialog_ui
	dialog = module.open_settings_dialog(frame)
	persist = Mock()
	monkeypatch.setattr(dialog, "_collect_values", lambda: "draft")
	monkeypatch.setattr(dialog, "_persist", persist)
	dialog.onApply(wx.CommandEvent())
	assert dialog.IsShown()
	persist.assert_called_once_with("draft")
	dialog.onCancel(wx.CommandEvent())
	pump_events()
	assert persist.call_count == 1
