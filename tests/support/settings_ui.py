"""Load real settings panels with NVDA's process-owned dialog shell replaced."""
from __future__ import annotations

import types
import sys
import wx

from tests.support.bootstrap import load_addon_module


def load_settings_ui(monkeypatch, *, real_dialog_shell=False):
	class BoxSizerHelper:
		def __init__(self, parent, orientation=None, *, sizer=None):
			self.parent = parent
			self.sizer = sizer if sizer is not None else wx.BoxSizer(orientation)

		def addItem(self, item, **kwargs):
			self.sizer.Add(item.sizer if isinstance(item, BoxSizerHelper) else item, **({"flag": wx.EXPAND} | kwargs))
			return item

		def addLabeledControl(self, label, control_class, **kwargs):
			row = wx.BoxSizer(wx.VERTICAL)
			row.Add(wx.StaticText(self.parent, label=label))
			control = control_class(self.parent, **kwargs)
			row.Add(control, 1, wx.EXPAND)
			self.sizer.Add(row, 0, wx.EXPAND)
			return control

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
	gui._isDebug = lambda: False
	gui.guiHelper.BORDER_FOR_DIALOGS = 8
	settings_dialogs = types.ModuleType("gui.settingsDialogs")
	settings_dialogs.SettingsDialog = _load_nvda_dialog_shell(gui) if real_dialog_shell else wx.Dialog
	monkeypatch.setitem(sys.modules, "gui", gui)
	monkeypatch.setitem(sys.modules, "gui.settingsDialogs", settings_dialogs)
	addon_handler = types.ModuleType("addonHandler")
	addon_handler.initTranslation = lambda: None
	monkeypatch.setitem(sys.modules, "addonHandler", addon_handler)
	return load_addon_module("ui.settings_panel", namespace="settings_ui_behavior_testpkg")


def _load_nvda_dialog_shell(gui):
	"""Use pinned NVDA dialog lifecycle definitions without its process-only mixins."""
	import ast
	import __future__
	from abc import abstractmethod
	from enum import IntEnum
	import time
	import weakref
	from logHandler import log
	from tests.support.bootstrap import PROJECT_ROOT
	path = PROJECT_ROOT.parent / "nvda/source/gui/settingsDialogs.py"
	tree = ast.parse(path.read_text(encoding="utf-8"))
	definition = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "SettingsDialog")
	definition.bases = [ast.Attribute(value=ast.Name(id="wx", ctx=ast.Load()), attr="Dialog", ctx=ast.Load())]
	definition.keywords = []
	module = ast.fix_missing_locations(ast.Module(body=[definition], type_ignores=[]))
	namespace = dict(wx=wx, gui=gui, guiHelper=gui.guiHelper, log=log,
		weakref=weakref, IntEnum=IntEnum, time=time, abstractmethod=abstractmethod)
	exec(compile(module, str(path), "exec", flags=__future__.annotations.compiler_flag), namespace)
	return namespace["SettingsDialog"]
