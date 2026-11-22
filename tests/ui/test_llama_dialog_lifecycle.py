from types import SimpleNamespace
from unittest.mock import Mock
import threading

import pytest
import wx

from tests.support import load_addon_module
from tests.support.settings_ui import load_settings_ui


@pytest.fixture
def editor(monkeypatch):
	app = wx.App.Get() or wx.App(False)
	load_settings_ui(monkeypatch)
	module = load_addon_module("ui.llama_preset_dialog", namespace="llama_dialog_lifecycle")
	monkeypatch.setattr(module.LlamaPresetDialog, "_scan_cache", lambda *_: None)
	provider = SimpleNamespace(create_preset=Mock(), update_preset=Mock())
	dialog = module.LlamaPresetDialog(None, provider)
	try:
		yield dialog, provider
	finally:
		if dialog:
			dialog.Destroy()
		wx.CallLater(20, app.ExitMainLoop)
		app.MainLoop()


def test_cancel_is_named_cancel_and_disposes_scan_without_saving(editor):
	dialog, provider = editor
	assert dialog.FindWindow(wx.ID_CANCEL).GetLabelText() == "Cancel"
	task = SimpleNamespace(cancel=Mock())
	dialog._cache_task = task
	wx.CallAfter(lambda: dialog.FindWindow(wx.ID_CANCEL).Command(wx.CommandEvent(wx.EVT_BUTTON.typeId, wx.ID_CANCEL)))
	assert dialog.ShowModal() == wx.ID_CANCEL
	assert dialog._closed
	task.cancel.assert_called_once()
	provider.create_preset.assert_not_called()


def test_runtime_validation_targets_runtime_page(editor):
	dialog, _ = editor
	dialog._name.SetValue("Example")
	dialog._main_manual.SetValue("owner/model")
	dialog._advanced.SetValue("not-an-option = 1")
	problems = dialog._problems_for()
	assert problems
	assert problems[0][0].startswith("Runtime options:")
	problems[0][1]()
	assert dialog._tabs.GetSelection() == 1


def test_problem_list_selects_first_problem(editor):
	dialog, _ = editor
	dialog._show_problems([("Missing name", Mock())])
	assert dialog._problems.GetSelection() == 0


def test_ok_saves_once_and_disposes_scan(editor):
	dialog, provider = editor
	dialog._name.SetValue("Example")
	dialog._main_manual.SetValue("owner/model")
	task = SimpleNamespace(cancel=Mock())
	dialog._cache_task = task
	wx.CallAfter(lambda: dialog._on_ok(None))
	assert dialog.ShowModal() == wx.ID_OK
	provider.create_preset.assert_called_once()
	task.cancel.assert_called_once()
	assert dialog._closed


def test_save_captures_values_and_detaches_without_cancelling(editor, monkeypatch):
	dialog, provider = editor
	module = __import__(dialog.__module__, fromlist=["background_tasks"])
	dialog._name.SetValue("Example")
	dialog._main_manual.SetValue("owner/model")
	queued = []
	handle = SimpleNamespace(cancel=Mock(), detach=Mock())
	monkeypatch.setattr(module.background_tasks, "submit", lambda work, **callbacks: queued.append((work, callbacks)) or handle)
	dialog._on_ok(None)
	dialog._on_ok(None)
	assert len(queued) == 1
	provider.create_preset.assert_not_called()
	dialog._main_manual.SetValue("owner/changed")
	dialog._dispose()
	handle.detach.assert_called_once()
	handle.cancel.assert_not_called()
	work, _callbacks = queued[0]
	worker = threading.Thread(target=lambda: work(threading.Event()))
	worker.start()
	worker.join(2)
	assert not worker.is_alive()
	assert provider.create_preset.call_args.args[0] == "owner/model"


def test_duplicate_is_background_work_and_close_only_detaches(monkeypatch):
	app = wx.App.Get() or wx.App(False)
	load_settings_ui(monkeypatch)
	module = load_addon_module("ui.llama_model_manager", namespace="llama_manager_mutation_test")
	monkeypatch.setattr(module.LlamaModelsDialog, "_refresh", lambda *_: None)
	provider = SimpleNamespace(duplicate_preset=Mock())
	dialog = module.LlamaModelsDialog(None, provider)
	queued = []
	handle = SimpleNamespace(cancel=Mock(), detach=Mock())
	monkeypatch.setattr(module.background_tasks, "submit", lambda work, **callbacks: queued.append(work) or handle)
	monkeypatch.setattr(dialog, "_selected", lambda: SimpleNamespace(model_id="original", display_name="Original"))
	monkeypatch.setattr(dialog, "_selection_changed", lambda: None)
	monkeypatch.setattr(wx, "TextEntryDialog", lambda *args, **kwargs: SimpleNamespace(
		ShowModal=lambda: wx.ID_OK, GetValue=lambda: "copy", Destroy=lambda: None))
	try:
		dialog._duplicate(None)
		assert len(queued) == 1
		provider.duplicate_preset.assert_not_called()
		dialog._dispose()
		handle.detach.assert_called_once()
		handle.cancel.assert_not_called()
		worker = threading.Thread(target=lambda: queued[0](threading.Event()))
		worker.start()
		worker.join(2)
		assert not worker.is_alive()
		provider.duplicate_preset.assert_called_once_with("original", "copy", "Original copy")
	finally:
		dialog.Destroy()
		wx.CallLater(20, app.ExitMainLoop)
		app.MainLoop()


def test_titlebar_close_discards_without_destroying_modal_wrapper(editor):
	dialog, provider = editor
	wx.CallAfter(dialog.Close)
	assert dialog.ShowModal() == wx.ID_CANCEL
	assert dialog
	assert dialog._closed
	provider.create_preset.assert_not_called()


def test_source_radio_selection_keeps_keyboard_focus(editor):
	dialog, _ = editor
	dialog.Show()
	dialog._main_mode_box.SetFocus()
	dialog._main_mode_box.SetSelection(1)
	dialog._on_main_mode()
	wx.App.Get().ProcessPendingEvents()
	assert wx.Window.FindFocus() is dialog._main_mode_box


def test_runtime_edit_updates_preview_and_moe_layers_availability(editor):
	dialog, _ = editor
	dialog._main_manual.SetValue("owner/model")
	assert not dialog._moe_layers.IsEnabled()
	dialog._layers.SetValue("12")
	assert "gpu-layers = 12" in dialog._preview.GetValue()
	dialog._moe.SetSelection(2)
	event = wx.CommandEvent(wx.EVT_CHOICE.typeId, dialog._moe.GetId())
	event.SetInt(2)
	dialog._moe.Command(event)
	assert dialog._moe_layers.IsEnabled()


def test_requested_runtime_fields_are_saved_and_previewed(editor):
	dialog, provider = editor
	dialog._name.SetValue("MoE preset")
	dialog._main_manual.SetValue("owner/model")
	dialog._moe_cache_mib.SetValue("3264")
	dialog._moe_cpu_share.SetValue("0.95")
	dialog._layers.SetValue("99")
	dialog._fa.SetSelection(2)
	dialog._ctx.SetValue(4096)
	dialog._n_predict.SetValue("512")
	dialog._on_change()
	expected = {
		"moe-cache-mib": "3264", "moe-cache-cpu-share": "0.95",
		"gpu-layers": "99", "flash-attn": "on", "ctx-size": "4096", "n-predict": "512",
	}
	assert dialog._options() == expected
	for key, value in expected.items():
		assert f"{key} = {value}" in dialog._preview.GetValue()
	wx.CallAfter(lambda: dialog._on_ok(None))
	assert dialog.ShowModal() == wx.ID_OK
	assert provider.create_preset.call_args.kwargs["options"] == expected


@pytest.mark.parametrize("attribute,value", [
	("_moe_cache_mib", "-1"), ("_moe_cache_mib", "1.5"),
	("_moe_cpu_share", "1.01"), ("_moe_cpu_share", "nan"),
	("_n_predict", "-2"),
])
def test_new_runtime_fields_validate_ranges(editor, attribute, value):
	dialog, _ = editor
	getattr(dialog, attribute).SetValue(value)
	with pytest.raises(ValueError):
		dialog._options()


def test_optional_runtime_fields_preserve_zero_and_reset_to_unspecified(editor):
	dialog, _ = editor
	dialog._moe_cache_mib.SetValue("0")
	dialog._moe_cpu_share.SetValue("0")
	dialog._n_predict.SetValue("-1")
	options = dialog._options()
	assert options["moe-cache-mib"] == "0"
	assert options["moe-cache-cpu-share"] == "0.0"
	assert options["n-predict"] == "-1"
	dialog._reset_runtime(None)
	assert not {"moe-cache-mib", "moe-cache-cpu-share", "n-predict"} & dialog._options().keys()


def test_saved_runtime_values_reopen_in_dedicated_fields(editor):
	dialog, provider = editor
	module = __import__(dialog.__module__, fromlist=["LlamaModelRecord"])
	options = {"moe-cache-mib": "3264", "moe-cache-cpu-share": "0.95", "n-predict": "512"}
	record = module.LlamaModelRecord("example", "owner/model", preset_options=options, display_name="Example")
	reopened = module.LlamaPresetDialog(None, provider, record)
	try:
		assert reopened._moe_cache_mib.GetValue() == "3264"
		assert reopened._moe_cpu_share.GetValue() == "0.95"
		assert reopened._n_predict.GetValue() == "512"
		assert reopened._advanced.GetValue() == ""
		assert all(reopened._options()[key] == value for key, value in options.items())
	finally:
		reopened.Destroy()
