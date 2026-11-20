import sys
from types import SimpleNamespace, ModuleType
from unittest.mock import Mock
from types import MethodType

import pytest

from tests.support import load_addon_module
from tests.support.settings_ui import load_settings_ui


@pytest.fixture
def module(monkeypatch):
	load_settings_ui(monkeypatch)
	helper = sys.modules["gui"].guiHelper
	helper.LabeledControlHelper = object
	monkeypatch.setitem(sys.modules, "gui.guiHelper", helper)
	speech = ModuleType("provider_connection_ui_testpkg.ui.nvda_ui")
	speech.message = Mock()
	monkeypatch.setitem(sys.modules, speech.__name__, speech)
	return load_addon_module("ui.provider_configure", namespace="provider_connection_ui_testpkg")


def test_result_is_announced_without_changing_focus(module, monkeypatch):
	announce = Mock()
	monkeypatch.setattr(module.nvda_ui, "message", announce)
	dialog = SimpleNamespace(_destroyed=False, _test_task=object(), _test_result=Mock(), _test_btn=Mock(),
		Layout=Mock(), IsActive=lambda: True)
	module.ProviderConfigureDialog._test_done(dialog, True, "Connection successful")
	assert dialog._test_task is None
	dialog._test_result.SetLabel.assert_called_once_with("Connection successful")
	dialog._test_btn.Enable.assert_called_once()
	announce.assert_called_once_with("Connection successful")


def test_completion_does_not_touch_closed_dialog_or_interrupt_another_window(module, monkeypatch):
	announce = Mock()
	monkeypatch.setattr(module.nvda_ui, "message", announce)
	dialog = SimpleNamespace(_destroyed=False, _test_task=object(), _test_result=Mock(), _test_btn=Mock(),
		Layout=Mock(), IsActive=lambda: False)
	module.ProviderConfigureDialog._test_done(dialog, False, "Offline")
	announce.assert_not_called()
	dialog._destroyed = True
	dialog._test_result.reset_mock()
	module.ProviderConfigureDialog._test_done(dialog, False, "Late failure")
	dialog._test_result.SetLabel.assert_not_called()


def test_button_dispatches_draft_test_and_delivers_failure(module, monkeypatch):
	callbacks = {}
	draft = object()
	def submit(work, **kwargs):
		callbacks.update(kwargs)
		callbacks["work"] = work
		return "task handle"
	monkeypatch.setattr(module.background_tasks, "submit", submit)
	monkeypatch.setattr(module.nvda_ui, "message", Mock())
	dialog = SimpleNamespace(_destroyed=False, _provider_name="OpenAI", _test_result=Mock(), _test_btn=Mock(),
		Layout=Mock(), IsActive=lambda: True, _draft_config=lambda: draft,
		_run_test=Mock(side_effect=RuntimeError("offline")))
	dialog._test_done = MethodType(module.ProviderConfigureDialog._test_done, dialog)
	module.ProviderConfigureDialog._on_test_connection(dialog, None)
	dialog._test_btn.Disable.assert_called_once()
	assert dialog._test_task == "task handle"
	with pytest.raises(RuntimeError, match="offline"):
		callbacks["work"](None)
	dialog._run_test.assert_called_once_with(draft)
	callbacks["on_error"](RuntimeError("offline"))
	assert "offline" in dialog._test_result.SetLabel.call_args.args[0]
	dialog._test_btn.Enable.assert_called_once()
