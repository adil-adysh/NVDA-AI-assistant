"""Load real settings panels with NVDA's process-owned dialog shell replaced."""
from __future__ import annotations

import types
import sys
import wx

from tests.support.bootstrap import load_addon_module


def load_settings_ui(monkeypatch):
	class BoxSizerHelper:
		def __init__(self, parent, orientation=None, *, sizer=None):
			self.sizer = sizer if sizer is not None else wx.BoxSizer(orientation)

		def addItem(self, item):
			self.sizer.Add(item.sizer if isinstance(item, BoxSizerHelper) else item, flag=wx.EXPAND)
			return item

	gui = types.ModuleType("gui")
	gui.guiHelper = types.SimpleNamespace(BoxSizerHelper=BoxSizerHelper)
	settings_dialogs = types.ModuleType("gui.settingsDialogs")
	settings_dialogs.SettingsDialog = wx.Dialog
	monkeypatch.setitem(sys.modules, "gui", gui)
	monkeypatch.setitem(sys.modules, "gui.settingsDialogs", settings_dialogs)
	addon_handler = types.ModuleType("addonHandler")
	addon_handler.initTranslation = lambda: None
	monkeypatch.setitem(sys.modules, "addonHandler", addon_handler)
	return load_addon_module("ui.settings_panel", namespace="settings_ui_behavior_testpkg")
