# -*- coding: utf-8 -*-
"""Provider management dialog — the primary provider administration UI.

Shows every provider as an entity with its name, type (cloud/local),
lifecycle state, and the actions valid for that state.  Selecting a
provider reveals its applicable actions:

- ``Install`` — local providers that are not yet installed.
- ``Configure`` — opens the provider-specific Configure dialog.
- ``Manage Models`` — opens the provider-specific model manager.

Unavailable actions are not rendered at all (no disabled stubs), and
all state is exposed as accessible text — never as visual-only
indicators.
"""

from __future__ import annotations

import builtins
import threading
from collections.abc import Callable
from typing import cast

import wx
from gui import guiHelper
from logHandler import log

from ..providers.registry import (
	ProviderAction,
	ProviderInfo,
	get_provider_infos,
	install_provider,
	provider_kind_label,
	provider_state_label,
)
from .model_manager import open_model_manager
from .provider_configure import build_configure_dialog


def _translate(message: str) -> str:
	return message


_ = cast(Callable[[str], str], getattr(builtins, "_", _translate))


class ProviderManagementDialog(wx.Dialog):
	# TRANSLATORS: Title of the AI provider management dialog.
	_TITLE = _("AI Assistant — Manage AI Providers")

	def __init__(self, parent: wx.Window) -> None:
		super().__init__(
			parent,
			title=_(self._TITLE),
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
		)
		self._provider_infos: list[ProviderInfo] = []
		self._install_active = False

		self._build_ui()
		self._refresh_provider_list()
		self.CentreOnScreen()

	# ------------------------------------------------------------------
	# UI construction
	# ------------------------------------------------------------------

	def _build_ui(self) -> None:
		main_sizer = wx.BoxSizer(wx.VERTICAL)
		s_helper = guiHelper.BoxSizerHelper(self, sizer=main_sizer)

		# TRANSLATORS: Instructions shown at the top of the provider management dialog.
		s_helper.addItem(
			wx.StaticText(
				self,
				label=_(
					"Select a provider to see the actions available for it."
				),
			)
		)
		s_helper.sizer.AddSpacer(8)

		# ── Provider list ─────────────────────────────────────────
		self._list = wx.ListCtrl(
			self,
			style=(wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_HRULES | wx.LC_VRULES),
		)
		# TRANSLATORS: Column header for the provider name in the provider list.
		self._list.AppendColumn(_("Provider"), width=160)
		# TRANSLATORS: Column header for the provider type (cloud/local) in the provider list.
		self._list.AppendColumn(_("Type"), width=90)
		# TRANSLATORS: Column header for the provider status in the provider list.
		self._list.AppendColumn(_("Status"), width=160)
		self._list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_selection_change)
		self._list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self._on_selection_change)
		s_helper.addItem(self._list, flag=wx.EXPAND, proportion=1)
		s_helper.sizer.AddSpacer(8)

		# ── Action buttons (shown per provider state) ─────────────
		button_sizer = wx.BoxSizer(wx.HORIZONTAL)

		# TRANSLATORS: Button that installs the selected local provider; {name} is the provider name.
		self._install_btn = wx.Button(self, label="")
		self._install_btn.Bind(wx.EVT_BUTTON, self._on_install)
		button_sizer.Add(self._install_btn, flag=wx.RIGHT, border=5)

		# TRANSLATORS: Button that configures the selected provider; {name} is the provider name.
		self._configure_btn = wx.Button(self, label="")
		self._configure_btn.Bind(wx.EVT_BUTTON, self._on_configure)
		button_sizer.Add(self._configure_btn, flag=wx.RIGHT, border=5)

		# TRANSLATORS: Button that opens the model manager for the selected provider; {name} is the provider name.
		self._manage_btn = wx.Button(self, label="")
		self._manage_btn.Bind(wx.EVT_BUTTON, self._on_manage_models)
		button_sizer.Add(self._manage_btn)

		s_helper.addItem(button_sizer)

		# ── Install progress ──────────────────────────────────────
		self._progress_label = wx.StaticText(self, label="")
		self._progress_label.Hide()
		self._progress_gauge = wx.Gauge(self, range=100, size=(-1, 20))
		self._progress_gauge.Hide()
		s_helper.addItem(self._progress_label)
		s_helper.addItem(self._progress_gauge, flag=wx.EXPAND)

		# ── Close button ──────────────────────────────────────────
		close_sizer = guiHelper.ButtonHelper(wx.HORIZONTAL)
		close_sizer.addButton(self, wx.ID_CLOSE, label="")
		self.Bind(wx.EVT_BUTTON, self._on_close, id=wx.ID_CLOSE)
		self.Bind(wx.EVT_CLOSE, self._on_close)
		s_helper.addDialogDismissButtons(close_sizer, separated=True)

		self.SetSizer(main_sizer)
		main_sizer.Fit(self)
		self.SetMinSize(self.scaleSize((620, 420)))

	def scaleSize(self, size: tuple[int, int]) -> wx.Size:
		return wx.Size(*size)

	# ------------------------------------------------------------------
	# Provider list
	# ------------------------------------------------------------------

	def _refresh_provider_list(self) -> None:
		"""Re-derive provider states and repopulate the list."""
		prev_id = self._selected_info().id if self._selected_info() is not None else None
		self._provider_infos = list(get_provider_infos())
		self._list.DeleteAllItems()
		target = 0
		for i, info in enumerate(self._provider_infos):
			idx = self._list.InsertItem(self._list.GetItemCount(), info.name)
			self._list.SetItem(idx, 1, provider_kind_label(info.kind))
			self._list.SetItem(idx, 2, provider_state_label(info.state))
			if info.id == prev_id:
				target = i
		if self._provider_infos:
			self._list.Select(target, on=1)
		self._update_actions()

	def _selected_info(self) -> ProviderInfo | None:
		sel = self._list.GetFirstSelected()
		if sel < 0 or sel >= len(self._provider_infos):
			return None
		return self._provider_infos[sel]

	def _on_selection_change(self, _event: wx.ListEvent) -> None:
		self._update_actions()

	def _update_actions(self) -> None:
		"""Show only the actions valid for the selected provider's state."""
		info = self._selected_info()
		if info is None:
			for btn in (self._install_btn, self._configure_btn, self._manage_btn):
				btn.Hide()
			self.Layout()
			return

		actions = set(info.actions)
		self._install_btn.SetLabel(
			_("&Install {name}").format(name=info.name),
		)
		self._install_btn.Show(ProviderAction.INSTALL in actions)
		self._configure_btn.SetLabel(
			_("&Configure {name}").format(name=info.name),
		)
		self._configure_btn.Show(ProviderAction.CONFIGURE in actions)
		self._manage_btn.SetLabel(
			_("&Manage {name} Models").format(name=info.name),
		)
		self._manage_btn.Show(ProviderAction.MANAGE_MODELS in actions)
		self.Layout()

	# ------------------------------------------------------------------
	# Actions
	# ------------------------------------------------------------------

	def _on_configure(self, _event: wx.CommandEvent) -> None:
		info = self._selected_info()
		if info is None or ProviderAction.CONFIGURE not in info.actions:
			return
		dlg = build_configure_dialog(self, info.id, info.name)
		try:
			if dlg.ShowModal() == wx.ID_OK:
				# Configuration may have changed the provider state.
				self._refresh_provider_list()
		finally:
			dlg.Destroy()

	def _on_manage_models(self, _event: wx.CommandEvent) -> None:
		info = self._selected_info()
		if info is None or ProviderAction.MANAGE_MODELS not in info.actions:
			return
		open_model_manager(self, info.id)
		# Setting an active model may complete a provider's configuration
		# (e.g. LiteRT-LM Installed -> Configured), so re-derive state.
		self._refresh_provider_list()

	def _on_install(self, _event: wx.CommandEvent) -> None:
		info = self._selected_info()
		if info is None or ProviderAction.INSTALL not in info.actions:
			return
		if self._install_active:
			return
		self._install_active = True
		self._install_btn.Disable()
		# TRANSLATORS: Progress message shown while installing a provider runtime; {name} is the provider name.
		self._progress_label.SetLabel(
			_("Installing {name}...").format(name=info.name),
		)
		self._progress_label.Show()
		self._progress_gauge.SetValue(0)
		self._progress_gauge.Show()
		self.Layout()

		def worker() -> None:
			try:
				# Broad catch is deliberate: an install failure must never crash
				# the dialog thread; it is reported to the user and the provider
				# stays in its current state.
				# pylint: disable=broad-exception-caught
				def progress(msg: str) -> None:
					wx.CallAfter(self._progress_label.SetLabel, msg)

				def bytes_progress(downloaded: int, total: int) -> None:
					wx.CallAfter(self._on_bytes_progress, downloaded, total)

				install_provider(
					info.id,
					on_progress=progress,
					on_bytes_progress=bytes_progress,
				)
				# TRANSLATORS: Success message after installing a provider runtime; {name} is the provider name.
				success_msg = _("{name} installed successfully.").format(name=info.name)
				wx.CallAfter(self._on_install_done, True, success_msg)
			except Exception as exc:
				log.error("Provider installation failed for %s: %s", info.id, exc)
				# TRANSLATORS: Error message after a provider runtime installation fails; {name} is the provider name and {error} the reason.
				fail_msg = _("{name} installation failed: {error}").format(
					name=info.name,
					error=exc,
				)
				wx.CallAfter(self._on_install_done, False, fail_msg)

		thread = threading.Thread(target=worker, daemon=True)
		thread.start()

	def _on_bytes_progress(self, downloaded: int, total: int) -> None:
		if total and total > 0:
			pct = min(downloaded * 100 // total, 100)
			self._progress_gauge.SetRange(100)
			self._progress_gauge.SetValue(pct)
		else:
			val = self._progress_gauge.GetValue()
			self._progress_gauge.SetValue(0 if val >= 100 else val + 5)

	def _on_install_done(self, success: bool, message: str) -> None:
		self._install_active = False
		self._progress_gauge.Hide()
		self._progress_label.Hide()
		# TRANSLATORS: Title of the installation result message box.
		icon = wx.ICON_INFORMATION if success else wx.ICON_ERROR
		wx.MessageBox(message, _("Provider Installation"), icon)
		self._refresh_provider_list()

	def _on_close(self, _event: wx.Event) -> None:
		self.EndModal(wx.ID_CANCEL)


def open_provider_dialog(parent: wx.Window) -> None:
	"""Open the provider management dialog (modal)."""
	dlg = ProviderManagementDialog(parent)
	try:
		dlg.ShowModal()
	finally:
		dlg.Destroy()
