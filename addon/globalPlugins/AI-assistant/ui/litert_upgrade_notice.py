# -*- coding: utf-8 -*-
"""Release-scoped, modeless LiteRT-LM runtime upgrade notice."""
from __future__ import annotations

import builtins
from collections.abc import Callable
from typing import cast

import addonHandler
import gui
import wx

from ..config.settings import (
	get_enabled_providers,
	get_litert_upgrade_notice_suppressed_version,
	set_litert_upgrade_notice_suppressed_version,
)


def _translate(message: str) -> str:
	return message


_ = cast(Callable[[str], str], getattr(builtins, "_", _translate))
_active_notice: wx.Dialog | None = None


def _current_addon_version() -> str:
	"""Read this add-on's installed version from NVDA's code add-on metadata."""
	try:
		addon = addonHandler.getCodeAddon()
		manifest = getattr(addon, "manifest", {})
		if isinstance(manifest, dict):
			version = manifest.get("addon_version") or manifest.get("version")
			if version:
				return str(version)
		version = getattr(addon, "version", "")
		return str(version or "")
	except Exception:
		return ""


class LiteRTUpgradeNotice(wx.Dialog):
	"""Nonmodal startup notice with direct upgrade and dismissal actions."""

	def __init__(self, parent: wx.Window, *, cleanup_pending: bool, version: str) -> None:
		title = _("LiteRT-LM Runtime Cleanup") if cleanup_pending else _("LiteRT-LM Runtime Upgrade Available")
		super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE)
		self._version = version
		self._cleanup_pending = cleanup_pending

		message = (
			_(
				"The LiteRT-LM runtime upgrade is installed, but cleanup of the previous runtime is still pending. "
				"Retry cleanup now, or choose Later."
			)
			if cleanup_pending
			else _("A newer LiteRT-LM runtime is available. Upgrade it now, or choose Later.")
		)
		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.Add(wx.StaticText(self, label=message), flag=wx.ALL | wx.EXPAND, border=12)

		# TRANSLATORS: Checkbox that suppresses the LiteRT-LM notice until a newer add-on release is installed.
		self._suppress_checkbox = wx.CheckBox(self, label=_("Don't remind me again until the next release"))
		sizer.Add(self._suppress_checkbox, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=12)

		buttons = wx.BoxSizer(wx.HORIZONTAL)
		# TRANSLATORS: Starts the LiteRT-LM runtime upgrade from the startup notice.
		action_label = _("Retry LiteRT-LM Cleanup") if cleanup_pending else _("Upgrade LiteRT-LM Runtime")
		self._upgrade_button = wx.Button(self, label=action_label)
		self._upgrade_button.Bind(wx.EVT_BUTTON, self._on_upgrade)
		buttons.Add(self._upgrade_button, flag=wx.RIGHT, border=8)
		# TRANSLATORS: Dismisses the LiteRT-LM upgrade notice.
		later_button = wx.Button(self, wx.ID_CLOSE, label=_("Later"))
		later_button.Bind(wx.EVT_BUTTON, self._on_close)
		buttons.Add(later_button)
		sizer.Add(buttons, flag=wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, border=12)

		self.SetSizerAndFit(sizer)
		self.SetMinSize(self.GetSize())
		self.SetEscapeId(wx.ID_CLOSE)
		self.CentreOnParent()
		self.Bind(wx.EVT_CLOSE, self._on_close)
		self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)

	def _remember_suppression(self) -> None:
		if self._suppress_checkbox.IsChecked() and self._version:
			set_litert_upgrade_notice_suppressed_version(self._version)

	def _on_close(self, _event: wx.Event) -> None:
		global _active_notice  # pylint: disable=global-statement
		self._remember_suppression()
		if _active_notice is self:
			_active_notice = None
		self.Destroy()

	def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
		global _active_notice  # pylint: disable=global-statement
		if event.GetEventObject() is self and _active_notice is self:
			_active_notice = None
		event.Skip()

	def _on_upgrade(self, _event: wx.CommandEvent) -> None:
		global _active_notice  # pylint: disable=global-statement
		self._remember_suppression()
		if _active_notice is self:
			_active_notice = None
		cleanup_pending = self._cleanup_pending
		self.Destroy()
		from .provider_dialog import run_litert_runtime_action

		wx.CallAfter(lambda: run_litert_runtime_action(gui.mainFrame, cleanup_pending=cleanup_pending))


def show_litert_upgrade_notice(*, cleanup_pending: bool = False) -> None:
	"""Show a modeless release-scoped notice; startup remains interactive."""
	global _active_notice  # pylint: disable=global-statement
	if "litert-lm" not in get_enabled_providers():
		return
	version = _current_addon_version()
	if version and get_litert_upgrade_notice_suppressed_version() == version:
		return
	if _active_notice is not None:
		if _active_notice.IsShown():
			_active_notice.Raise()
			return
		_active_notice = None

	dialog = LiteRTUpgradeNotice(gui.mainFrame, cleanup_pending=cleanup_pending, version=version)
	_active_notice = dialog
	dialog.Show()
	dialog.Raise()
