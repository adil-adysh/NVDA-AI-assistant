"""Real wx provider controls keep startup changes as drafts until Save."""
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest
import wx

from tests.support import load_addon_module
from tests.support.settings_ui import load_settings_ui


@pytest.fixture
def provider_ui(monkeypatch):
	app = wx.App.Get() or wx.App(False)
	load_settings_ui(monkeypatch)
	helper = sys.modules["gui"].guiHelper
	monkeypatch.setitem(sys.modules, "gui.guiHelper", helper)
	speech = ModuleType("provider_startup_ui_testpkg.ui.nvda_ui")
	speech.message = Mock()
	monkeypatch.setitem(sys.modules, speech.__name__, speech)
	module = load_addon_module("ui.provider_configure", namespace="provider_startup_ui_testpkg")
	monkeypatch.setattr(module, "get_configure_fields", lambda *_: ())
	monkeypatch.setattr(module, "is_installable", lambda *_: False)
	monkeypatch.setattr(module, "build_provider_config", lambda provider: SimpleNamespace(provider=provider))
	dialogs = []
	def create(provider):
		dialog = module.ProviderConfigureDialog(None, provider, provider)
		dialogs.append(dialog)
		return dialog
	try:
		yield module, create
	finally:
		for dialog in dialogs:
			dialog.Destroy()
		app.ProcessPendingEvents()


@pytest.mark.parametrize("provider", ["litert-lm", "llama-cpp-server"])
def test_local_choice_exposes_two_modes_and_does_not_save_on_cancel(provider_ui, monkeypatch, provider):
	module, create = provider_ui
	monkeypatch.setattr(module, "get_local_startup_mode", lambda *_: "server")
	save = Mock()
	monkeypatch.setattr(module, "set_local_startup_mode", save)
	dialog = create(provider)
	assert dialog._startup_choice.GetCount() == 2
	assert dialog._startup_choice.GetSelection() == 1
	assert "Startup" in dialog._startup_choice.GetName()
	assert "active provider" in dialog._startup_choice.GetName()
	dialog._startup_choice.SetSelection(0)
	dialog.EndModal = Mock()
	dialog._on_cancel(None)
	save.assert_not_called()
	dialog.EndModal.assert_called_once_with(wx.ID_CANCEL)


@pytest.mark.parametrize("provider", ["openai", "ollama", "gemini"])
def test_remote_provider_has_no_startup_control(provider_ui, provider):
	_module, create = provider_ui
	assert create(provider)._startup_choice is None


@pytest.mark.parametrize("provider", ["litert-lm", "llama-cpp-server"])
def test_save_updates_only_this_provider_without_activation(provider_ui, monkeypatch, provider):
	module, create = provider_ui
	monkeypatch.setattr(module, "get_local_startup_mode", lambda *_: "lazy")
	save, save_connection = Mock(), Mock()
	monkeypatch.setattr(module, "set_local_startup_mode", save)
	monkeypatch.setattr(module, "set_openai_compat_config", save_connection)
	dialog = create(provider)
	dialog._startup_choice.SetSelection(1)
	dialog.EndModal = Mock()
	dialog._on_save(None)
	save.assert_called_once_with(provider, "server")
	assert save_connection.call_args.kwargs == {"activate": False}
	dialog.EndModal.assert_called_once_with(wx.ID_OK)


def test_invalid_startup_selection_keeps_dialog_open_and_saves_nothing(provider_ui, monkeypatch):
	module, create = provider_ui
	monkeypatch.setattr(module, "get_local_startup_mode", lambda *_: "lazy")
	save = Mock()
	monkeypatch.setattr(module, "set_openai_compat_config", save)
	monkeypatch.setattr(wx, "MessageBox", Mock())
	dialog = create("litert-lm")
	dialog._startup_choice.SetSelection(wx.NOT_FOUND)
	dialog.EndModal = Mock()
	dialog._on_save(None)
	save.assert_not_called()
	dialog.EndModal.assert_not_called()
