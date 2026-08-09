# -*- coding: utf-8 -*-
"""Model Manager dialog — browse, enable, download, and delete models.

Opened from the provider management dialog for a **specific provider**
(the provider is passed in; the dialog never asks the user to choose
one again).  Provides a model list grouped by priority and download
state, a details panel, and action buttons (download, delete, set
active, enable/disable) driven by the provider's model features.
"""

from __future__ import annotations

import threading
import wx

from gui import guiHelper
from logHandler import log

from ..providers.litert_models import recommended_models
from ..providers.model_manager import (
	ManagedModel,
	ModelManagerProvider,
	ModelState,
)
from ..providers.registry import (
	build_model_manager,
	model_manager_title,
	provider_display_name,
)
from .enabled_models import EnabledModelsStore

_RECOMMENDED_PRIORITY = 50


class ModelManagerDialog(wx.Dialog):
	"""Browse and manage models for a specific provider."""

	def __init__(
		self,
		parent: wx.Window,
		provider: ModelManagerProvider,
		provider_name: str,
	) -> None:
		super().__init__(
			parent,
			title=_(model_manager_title(provider_name)),
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
		)
		self._provider = provider
		self._provider_name = provider_name
		self._enabled_store = EnabledModelsStore()
		self._models: list[ManagedModel] = []
		self._displayed_models: list[ManagedModel] = []
		self._pending_downloads: set[str] = set()
		self._known_map = {m.filename: m for m in recommended_models()}

		self._build_ui()
		self._refresh_model_list()
		self.CentreOnScreen()

	# ------------------------------------------------------------------
	# UI construction
	# ------------------------------------------------------------------

	def _build_ui(self) -> None:
		main_sizer = wx.BoxSizer(wx.VERTICAL)
		s_helper = guiHelper.BoxSizerHelper(self, sizer=main_sizer)

		# ── Model list ───────────────────────────────────────────
		# TRANSLATORS: Label for the model list.
		list_label = wx.StaticText(self, label=_("Models:"))
		s_helper.addItem(list_label)

		self._list = wx.ListCtrl(
			self,
			style=(wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_HRULES | wx.LC_VRULES),
		)
		self._list.AppendColumn("", width=40)
		self._list.AppendColumn("", width=40)
		# TRANSLATORS: Column header for the model name.
		self._list.AppendColumn(_("Model"), width=280)
		# TRANSLATORS: Column header for the download status.
		self._list.AppendColumn(_("Status"), width=180)
		# TRANSLATORS: Column header for the model file size.
		self._list.AppendColumn(_("Size"), width=100)

		self._list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_selection_change)
		self._list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self._on_selection_change)
		self._list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_double_click)
		s_helper.addItem(self._list, flag=wx.EXPAND, proportion=1)
		s_helper.sizer.AddSpacer(8)

		# ── Model details panel ──────────────────────────────────
		# TRANSLATORS: Label for the selected model details section.
		details_label = wx.StaticText(
			self,
			label=_("Selected model details:"),
		)
		s_helper.addItem(details_label)

		self._details_text = wx.TextCtrl(
			self,
			style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_NONE,
			size=(-1, 80),
		)
		self._details_text.SetBackgroundColour(self.GetBackgroundColour())
		s_helper.addItem(self._details_text, flag=wx.EXPAND)
		s_helper.sizer.AddSpacer(8)

		# ── Show disabled checkbox ───────────────────────────────
		# TRANSLATORS: Checkbox to show disabled models.
		self._show_disabled_cb = wx.CheckBox(
			self,
			label=_("Show disabled models"),
		)
		self._show_disabled_cb.SetValue(True)
		self._show_disabled_cb.Bind(wx.EVT_CHECKBOX, self._on_show_disabled)
		s_helper.addItem(self._show_disabled_cb)

		# ── Action buttons ───────────────────────────────────────
		button_sizer = wx.BoxSizer(wx.HORIZONTAL)

		# TRANSLATORS: Button to download a model.
		self._download_btn = wx.Button(self, label=_("&Download"))
		self._download_btn.Bind(wx.EVT_BUTTON, self._on_download)
		button_sizer.Add(self._download_btn, flag=wx.RIGHT, border=5)

		# TRANSLATORS: Button to delete a downloaded model.
		self._delete_btn = wx.Button(self, label=_("&Delete"))
		self._delete_btn.Bind(wx.EVT_BUTTON, self._on_delete)
		button_sizer.Add(self._delete_btn, flag=wx.RIGHT, border=5)

		# TRANSLATORS: Button to set the selected model as active.
		self._set_active_btn = wx.Button(self, label=_("Set &Active"))
		self._set_active_btn.Bind(wx.EVT_BUTTON, self._on_set_active)
		button_sizer.Add(self._set_active_btn)

		# TRANSLATORS: Button to open the per-model Configure dialog.
		self._configure_btn = wx.Button(self, label=_("Configure &Model..."))
		self._configure_btn.Bind(wx.EVT_BUTTON, self._on_configure_model)
		button_sizer.Add(self._configure_btn, flag=wx.LEFT, border=5)

		s_helper.addItem(button_sizer)

		# ── Download progress bar ────────────────────────────────
		self._progress_gauge = wx.Gauge(
			self,
			range=100,
			size=(-1, 20),
		)
		self._progress_gauge.Hide()
		self._progress_label = wx.StaticText(self, label="")
		self._progress_label.Hide()
		s_helper.addItem(self._progress_label)
		s_helper.addItem(self._progress_gauge, flag=wx.EXPAND)

		# ── Close button ─────────────────────────────────────────
		close_sizer = guiHelper.ButtonHelper(wx.HORIZONTAL)
		close_sizer.addButton(self, wx.ID_CLOSE, label="")
		self.Bind(wx.EVT_BUTTON, self._on_close, id=wx.ID_CLOSE)
		self.Bind(wx.EVT_CLOSE, self._on_close)
		s_helper.addDialogDismissButtons(close_sizer, separated=True)

		self.SetSizer(main_sizer)
		main_sizer.Fit(self)
		self.SetMinSize(self.scaleSize((680, 550)))

	def scaleSize(self, size: tuple[int, int]) -> wx.Size:
		return wx.Size(*size)

	# ------------------------------------------------------------------
	# Model list refresh
	# ------------------------------------------------------------------

	def _refresh_model_list(self) -> None:
		"""Reload models from the provider and repopulate the list."""
		self._models = self._provider.list_managed_models()
		enabled_ids = self._enabled_store.get_enabled(self._provider.provider_id)

		# Separate by download state + priority
		recommended_ready: list[ManagedModel] = []
		recommended_download: list[ManagedModel] = []
		other_ready: list[ManagedModel] = []
		other_download: list[ManagedModel] = []

		show_disabled = self._show_disabled_cb.GetValue()

		for m in self._models:
			if not show_disabled and m.id not in enabled_ids:
				continue
			rec = m.priority <= _RECOMMENDED_PRIORITY
			ready = m.state.is_ready()

			if rec and ready:
				recommended_ready.append(m)
			elif rec:
				recommended_download.append(m)
			elif ready:
				other_ready.append(m)
			else:
				other_download.append(m)

		self._list.DeleteAllItems()
		self._displayed_models = recommended_ready + recommended_download + other_ready + other_download

		active_id = self._provider.active_model_id
		self._active_id_clean = active_id.strip() if isinstance(active_id, str) else None

		if recommended_ready:
			self._add_section_header(_("── Recommended — Ready to use ──"))
			self._add_models(recommended_ready, enabled_ids)
		if recommended_download:
			self._add_section_header(_("── Recommended — Available to download ──"))
			self._add_models(recommended_download, enabled_ids)
		if other_ready:
			self._add_section_header(_("── Other Models — Ready to use ──"))
			self._add_models(other_ready, enabled_ids)
		if other_download:
			self._add_section_header(_("── Other Models — Available to download ──"))
			self._add_models(other_download, enabled_ids)

		self._update_buttons()

	def _add_section_header(self, label: str) -> None:
		idx = self._list.InsertItem(self._list.GetItemCount(), label)
		font = self._list.GetFont()
		font.SetWeight(wx.FONTWEIGHT_BOLD)
		self._list.SetItemFont(idx, font)
		self._list.SetItemBackgroundColour(idx, wx.Colour(230, 230, 240))

	def _add_models(
		self,
		models: list[ManagedModel],
		enabled_ids: set[str],
	) -> None:
		for m in models:
			idx = self._list.InsertItem(self._list.GetItemCount(), "")

			# Column 0: enabled checkbox
			is_enabled = m.id in enabled_ids
			self._list.SetItem(idx, 0, "☑" if is_enabled else "☐")  # noqa: RUF001

			# Column 1: active marker
			is_active = _model_matches_active(m.id, self._active_id_clean)
			self._list.SetItem(idx, 1, "◉" if is_active else "○")  # noqa: RUF001

			# Column 2: display name
			self._list.SetItem(idx, 2, m.display_name)

			# Column 3: status
			self._list.SetItem(idx, 3, _status_label(m.state))

			# Column 4: size
			self._list.SetItem(idx, 4, m.size_hint)

			self._list.SetItemData(idx, idx)

	# ------------------------------------------------------------------
	# Button state
	# ------------------------------------------------------------------

	def _get_selected_model(self) -> ManagedModel | None:
		"""Return the currently selected model, skipping section headers."""
		sel = self._list.GetFirstSelected()
		if sel < 0:
			return None
		count = self._list.GetItemCount()
		model_idx = 0
		for i in range(count):
			if i == sel:
				if model_idx < len(self._displayed_models):
					# Verify this is a real model row, not a header
					if self._list.GetItemText(i, 3):  # has status → real model
						return self._displayed_models[model_idx]
				return None
			# Count non-header items
			if self._list.GetItemText(i, 3):  # has a status → real model
				model_idx += 1
		return None

	def _update_buttons(self) -> None:
		model = self._get_selected_model()
		if model is None:
			self._download_btn.Disable()
			self._delete_btn.Disable()
			self._set_active_btn.Disable()
			self._configure_btn.Disable()
			return

		can_dl = (
			self._provider.features.download
			and model.state == ModelState.NOT_DOWNLOADED
			and model.id not in self._pending_downloads
		)
		can_del = self._provider.features.delete and model.state == ModelState.DOWNLOADED

		self._download_btn.Enable(can_dl)
		self._delete_btn.Enable(can_del)
		self._set_active_btn.Enable(model.state.is_ready())
		self._configure_btn.Enable(True)

	def _update_details(self) -> None:
		model = self._get_selected_model()
		if model is None:
			self._details_text.SetValue("")
			return

		known = self._known_map.get(model.id)
		desc = known.description if known else ""
		caps = _capabilities_label(model)
		lines = [
			model.display_name,
			"",
			f"Size: {model.size_hint}",
			f"Status: {_status_label(model.state)}",
			f"Capabilities: {caps}",
		]
		if desc:
			lines.append("")
			lines.append(desc)
		self._details_text.SetValue("\n".join(lines))

	# ------------------------------------------------------------------
	# Event handlers
	# ------------------------------------------------------------------

	def _on_selection_change(self, event: wx.ListEvent) -> None:
		self._update_buttons()
		self._update_details()
		event.Skip()

	def _on_double_click(self, _event: wx.ListEvent) -> None:
		"""Double-click / Enter: toggle enabled, or set active if ready."""
		model = self._get_selected_model()
		if model is None:
			return
		is_enabled = self._enabled_store.is_enabled(
			self._provider.provider_id,
			model.id,
		)
		if is_enabled and model.state.is_ready():
			self._provider.set_active_model(model.id)
		else:
			self._toggle_enabled(model, not is_enabled)
		self._refresh_model_list()

	def _on_show_disabled(self, _event: wx.CommandEvent) -> None:
		self._refresh_model_list()

	def _on_download(self, _event: wx.CommandEvent) -> None:
		model = self._get_selected_model()
		if model is None:
			return
		self._pending_downloads.add(model.id)
		self._update_buttons()

		# Show the gauge
		self._progress_gauge.SetValue(0)
		self._progress_gauge.SetRange(100)
		self._progress_gauge.Show()
		self._progress_label.SetLabel(
			_("Downloading {}...").format(model.display_name),
		)
		self._progress_label.Show()
		self._list.Disable()
		self._download_btn.Disable()
		self.Layout()

		def worker() -> None:
			try:

				def progress(
					msg: str,
					downloaded: int | None,
					total: int | None,
				) -> None:
					wx.CallAfter(
						self._on_download_progress,
						model.id,
						msg,
						downloaded,
						total,
					)

				self._provider.download_model(model.id, on_progress=progress)
			except Exception as exc:
				log.error("Model download failed: %s", exc)
				err_msg = _("Download failed: {}").format(exc)
				wx.CallAfter(
					lambda: wx.MessageBox(
						err_msg,
						_("Error"),
						wx.ICON_ERROR,
					),
				)
			finally:
				wx.CallAfter(self._on_download_complete, model.id)

		thread = threading.Thread(target=worker, daemon=True)
		thread.start()

	def _on_download_progress(
		self,
		_model_id: str,
		msg: str,
		downloaded: int | None,
		total: int | None,
	) -> None:
		self._progress_label.SetLabel(msg)
		if total and total > 0 and downloaded is not None:
			pct = min(downloaded * 100 // total, 100)
			if self._progress_gauge.GetRange() != 100:
				self._progress_gauge.SetRange(100)
			self._progress_gauge.SetValue(pct)
		else:
			# Indeterminate: pulse the gauge
			val = self._progress_gauge.GetValue()
			self._progress_gauge.SetValue(0 if val >= 100 else val + 5)

	def _on_download_complete(self, model_id: str) -> None:
		self._pending_downloads.discard(model_id)
		self._progress_gauge.Hide()
		self._progress_label.Hide()
		self._list.Enable()
		self._refresh_model_list()

	def _on_delete(self, _event: wx.CommandEvent) -> None:
		model = self._get_selected_model()
		if model is None:
			return
		try:
			self._provider.delete_model(model.id)
		except Exception as exc:
			log.error("Model deletion failed: %s", exc)
			# TRANSLATORS: Error message when model deletion fails.
			wx.MessageBox(
				_("Failed to delete model: {}").format(exc),
				_("Error"),
				wx.ICON_ERROR,
			)
		self._refresh_model_list()

	def _on_set_active(self, _event: wx.CommandEvent) -> None:
		model = self._get_selected_model()
		if model is None or not model.state.is_ready():
			return
		self._provider.set_active_model(model.id)
		self._refresh_model_list()

	def _on_configure_model(self, _event: wx.CommandEvent) -> None:
		"""Open the per-model Configure dialog for the selected model."""
		model = self._get_selected_model()
		if model is None:
			return
		from .model_config_dialog import open_model_configure

		open_model_configure(
			self,
			self._provider.provider_id,
			model.id,
			model.display_name,
		)

	def _on_close(self, _event: wx.Event) -> None:
		self.EndModal(wx.ID_CANCEL)

	# ------------------------------------------------------------------
	# Helpers
	# ------------------------------------------------------------------

	def _toggle_enabled(self, model: ManagedModel, enabled: bool) -> None:
		self._enabled_store.set_enabled(
			self._provider.provider_id,
			model.id,
			enabled,
		)
		self._refresh_model_list()


# ── Module-level helpers ───────────────────────────────────────────


def _status_label(state: ModelState) -> str:
	"""Return a human-readable label for a model state."""
	if state == ModelState.DOWNLOADED:
		return "✅ Downloaded"  # noqa: RUF001
	if state == ModelState.NOT_DOWNLOADED:
		return "⬇️ Not downloaded"  # noqa: RUF001
	if state == ModelState.DOWNLOADING:
		return "⏳ Downloading..."  # noqa: RUF001
	if state == ModelState.FAILED:
		return "❌ Failed"  # noqa: RUF001
	if state == ModelState.READY:
		return "Available"
	return str(state.value)


def _model_matches_active(model_id: str, active_id: str | None) -> bool:
	"""Check if model_id matches the active model (loose comparison)."""
	if active_id is None:
		return False
	return (
		model_id == active_id
		or model_id.replace("-", "_") == active_id.replace("-", "_")
		or model_id.replace("-", "").casefold() == active_id.replace("-", "").casefold()
	)


def _capabilities_label(model: ManagedModel) -> str:
	"""Return a human-readable capabilities string."""
	parts: list[str] = []
	caps = set(model.capabilities)
	if "streaming" in caps:
		parts.append("Streaming")
	if "vision" in caps or "image_input" in caps:
		parts.append("Vision")
	if "chat" in caps:
		parts.append("Chat")
	if "completion" in caps:
		parts.append("Completion")
	if "tools" in caps:
		parts.append("Tools")
	return ", ".join(parts) if parts else "Text"


def open_model_manager(parent: wx.Window, provider_id: str) -> None:
	"""Open the model manager dialog for *provider_id*.

	The provider context is already known — the dialog manages that
	provider's models and never asks the user to choose a provider
	again.  Modal: returns when the dialog is closed.
	"""
	provider = build_model_manager(provider_id)
	dlg = ModelManagerDialog(
		parent,
		provider,
		provider_display_name(provider_id),
	)
	try:
		dlg.ShowModal()
	finally:
		dlg.Destroy()
