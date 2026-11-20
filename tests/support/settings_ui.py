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

		def addItem(self, item, **kwargs):
			self.sizer.Add(item.sizer if isinstance(item, BoxSizerHelper) else item, **({"flag": wx.EXPAND} | kwargs))
			return item

		def addDialogDismissButtons(self, buttons, separated=False):
			self.sizer.Add(buttons.sizer)

	class LabeledControlHelper:
		def __init__(self, parent, label, control_class, **kwargs):
			self.sizer = wx.BoxSizer(wx.HORIZONTAL)
			self.sizer.Add(wx.StaticText(parent, label=label))
			self.control = control_class(parent, **kwargs)
			self.sizer.Add(self.control)

	class ButtonHelper:
		def __init__(self, orientation):
			self.sizer = wx.BoxSizer(orientation)

		def addButton(self, parent, button_id, label):
			button = wx.Button(parent, button_id, label=label)
			self.sizer.Add(button)
			return button

	gui = types.ModuleType("gui")
	gui.guiHelper = types.SimpleNamespace(BoxSizerHelper=BoxSizerHelper,
		LabeledControlHelper=LabeledControlHelper, ButtonHelper=ButtonHelper)
	settings_dialogs = types.ModuleType("gui.settingsDialogs")
	settings_dialogs.SettingsDialog = wx.Dialog
	monkeypatch.setitem(sys.modules, "gui", gui)
	monkeypatch.setitem(sys.modules, "gui.settingsDialogs", settings_dialogs)
	addon_handler = types.ModuleType("addonHandler")
	addon_handler.initTranslation = lambda: None
	monkeypatch.setitem(sys.modules, "addonHandler", addon_handler)
	return load_addon_module("ui.settings_panel", namespace="settings_ui_behavior_testpkg")
