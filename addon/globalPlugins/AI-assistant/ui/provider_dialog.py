# -*- coding: utf-8 -*-
"""Provider management dialog — the primary provider administration UI.

Shows every provider as an entity with its name, type (cloud/local),
lifecycle state, enabled state, and whether it is the active provider.
Selecting a provider reveals its applicable actions:

- ``Install`` — local providers that are not yet installed.
- ``Configure`` — opens the provider-specific Configure dialog.
- ``Manage Models`` — opens the provider-specific model manager.
- ``Set as Active`` — makes the selected provider the active AI provider.
- ``Enable``/``Disable`` — toggles whether the provider is available.

Unavailable actions are not rendered at all (no disabled stubs), and
all state is exposed as accessible text — never as visual-only
indicators.
"""

from __future__ import annotations

import builtins
from collections.abc import Callable
from typing import cast

import wx
from gui import guiHelper
from logHandler import log

from ..config.settings import get_enabled_providers
from ..providers.registry import (
	ProviderAction,
	ProviderInfo,
	get_provider_infos,
	install_provider,
	provider_display_name,
	provider_kind_label,
	provider_state_label,
	set_active_provider,
	set_provider_enabled,
)
from .download_progress import DownloadProgressDialog
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
		self._list.AppendColumn(_("Provider"), width=150)
		# TRANSLATORS: Column header for the provider type (cloud/local) in the provider list.
		self._list.AppendColumn(_("Type"), width=80)
		# TRANSLATORS: Column header for the provider status in the provider list.
		self._list.AppendColumn(_("Status"), width=140)
		# TRANSLATORS: Column header for the provider enabled state in the provider list.
		self._list.AppendColumn(_("Enabled"), width=80)
		# TRANSLATORS: Column header marking the active provider in the provider list.
		self._list.AppendColumn(_("Active"), width=70)
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
		button_sizer.Add(self._manage_btn, flag=wx.RIGHT, border=5)

		# TRANSLATORS: Button that makes the selected provider the active AI provider.
		self._set_active_btn = wx.Button(self, label="")
		self._set_active_btn.Bind(wx.EVT_BUTTON, self._on_set_active)
		button_sizer.Add(self._set_active_btn, flag=wx.RIGHT, border=5)

		# TRANSLATORS: Button that enables or disables the selected provider.
		self._enable_btn = wx.Button(self, label="")
		self._enable_btn.Bind(wx.EVT_BUTTON, self._on_toggle_enabled)
		button_sizer.Add(self._enable_btn)

		s_helper.addItem(button_sizer)

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
			# TRANSLATORS: Value shown in the Enabled column when a provider is enabled.
			self._list.SetItem(idx, 3, _("Yes") if info.enabled else _("No"))
			# TRANSLATORS: Value shown in the Active column when a provider is the active one.
			self._list.SetItem(idx, 4, _("Yes") if info.active else "")
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
			for btn in (
				self._install_btn,
				self._configure_btn,
				self._manage_btn,
				self._set_active_btn,
				self._enable_btn,
			):
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

		# TRANSLATORS: Button that makes the selected provider the active AI provider.
		self._set_active_btn.SetLabel(_("&Set as Active"))
		self._set_active_btn.Show(info.enabled and not info.active)

		if info.enabled:
			# TRANSLATORS: Button that disables the selected provider; {name} is the provider name.
			self._enable_btn.SetLabel(_("&Disable {name}").format(name=info.name))
		else:
			# TRANSLATORS: Button that enables the selected provider; {name} is the provider name.
			self._enable_btn.SetLabel(_("&Enable {name}").format(name=info.name))
		self._enable_btn.Show(True)
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

	def _on_set_active(self, _event: wx.CommandEvent) -> None:
		info = self._selected_info()
		if info is None or not info.enabled or info.active:
			return
		try:
			# Broad catch is deliberate: persistence failures are surfaced
			# accessibly instead of crashing the dialog.
			# pylint: disable=broad-exception-caught
			set_active_provider(info.id)
		except Exception as exc:
			log.error("Failed to activate provider %s: %s", info.id, exc)
			wx.MessageBox(
				# TRANSLATORS: Error shown when activating a provider fails; {error} is the reason.
				_("Failed to activate provider: {}").format(exc),
				_("Error"),
				wx.ICON_ERROR,
			)
			return
		self._refresh_provider_list()

	def _on_toggle_enabled(self, _event: wx.CommandEvent) -> None:
		info = self._selected_info()
		if info is None:
			return
		if info.enabled:
			self._disable_provider(info)
		else:
			self._enable_provider(info)

	def _enable_provider(self, info: ProviderInfo) -> None:
		try:
			# Broad catch is deliberate: persistence failures are surfaced
			# accessibly instead of crashing the dialog.
			# pylint: disable=broad-exception-caught
			set_provider_enabled(info.id, True)
		except Exception as exc:
			log.error("Failed to enable provider %s: %s", info.id, exc)
			wx.MessageBox(
				# TRANSLATORS: Error shown when enabling a provider fails; {error} is the reason.
				_("Failed to enable provider: {}").format(exc),
				_("Error"),
				wx.ICON_ERROR,
			)
			return
		self._refresh_provider_list()

	def _disable_provider(self, info: ProviderInfo) -> None:
		"""Disable *info*, guarding the last-enabled and active providers."""
		other_enabled = [pid for pid in get_enabled_providers() if pid != info.id]
		if not other_enabled:
			wx.MessageBox(
				# TRANSLATORS: Error when trying to disable the last enabled provider.
				_("At least one provider must remain enabled."),
				_("Error"),
				wx.ICON_ERROR,
			)
			return
		if info.active:
			next_name = provider_display_name(other_enabled[0])
			if (
				wx.MessageBox(
					# TRANSLATORS: Confirmation when disabling the active provider; {name} is the provider being disabled and {next_name} the provider that will become active.
					_(
						"{name} is currently the active provider. Disabling it will "
						"switch the active provider to {next_name}. Continue?"
					).format(name=info.name, next_name=next_name),
					# TRANSLATORS: Title of the confirmation shown when disabling the active provider.
					_("Disable Active Provider"),
					wx.YES_NO | wx.ICON_WARNING,
				)
				!= wx.YES
			):
				return
			try:
				# Broad catch is deliberate: persistence failures are surfaced
				# accessibly instead of crashing the dialog.
				# pylint: disable=broad-exception-caught
				set_active_provider(other_enabled[0])
			except Exception as exc:
				log.error("Failed to switch active provider: %s", exc)
				wx.MessageBox(
					# TRANSLATORS: Error shown when switching the active provider fails; {error} is the reason.
					_("Failed to switch active provider: {}").format(exc),
					_("Error"),
					wx.ICON_ERROR,
				)
				return
		try:
			# Broad catch is deliberate: persistence failures are surfaced
			# accessibly instead of crashing the dialog.
			# pylint: disable=broad-exception-caught
			set_provider_enabled(info.id, False)
		except Exception as exc:
			log.error("Failed to disable provider %s: %s", info.id, exc)
			wx.MessageBox(
				# TRANSLATORS: Error shown when disabling a provider fails; {error} is the reason.
				_("Failed to disable provider: {}").format(exc),
				_("Error"),
				wx.ICON_ERROR,
			)
			return
		self._refresh_provider_list()

	def _on_install(self, _event: wx.CommandEvent) -> None:
		info = self._selected_info()
		if info is None or ProviderAction.INSTALL not in info.actions:
			return
		provider_id = info.id
		provider_name = info.name

		def worker(dlg: DownloadProgressDialog) -> None:
			def progress(msg: str) -> None:
				dlg.update_message(msg)

			def bytes_progress(downloaded: int, total: int) -> None:
				dlg.update_progress(downloaded, total)

			install_provider(
				provider_id,
				on_progress=progress,
				on_bytes_progress=bytes_progress,
				cancel_event=dlg.cancel_event,
			)
			# TRANSLATORS: Success message after installing a provider runtime; {name} is the provider name.
			dlg.signal_complete(
				True,
				_("{name} installed successfully.").format(name=provider_name),
			)

		DownloadProgressDialog.run(
			self,
			title=_("Provider Installation"),
			worker=worker,
			on_complete=self._refresh_provider_list,
			initial_message=_("Installing {name}...").format(name=provider_name),
		)

	def _on_close(self, _event: wx.Event) -> None:
		self.EndModal(wx.ID_CANCEL)


def open_provider_dialog(parent: wx.Window) -> None:
	"""Open the provider management dialog (modal)."""
	dlg = ProviderManagementDialog(parent)
	try:
		dlg.ShowModal()
	finally:
		dlg.Destroy()
