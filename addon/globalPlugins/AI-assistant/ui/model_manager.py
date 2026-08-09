# -*- coding: utf-8 -*-
"""Model Manager dialog — browse, enable, download, and delete models.

Opened from NVDA's Tools menu.  Provides a provider combo box, a model
list grouped by priority and download state, a details panel, and
action buttons (download, delete, set active, enable/disable).
"""

from __future__ import annotations

import threading
import wx

from gui import guiHelper
import gui
from logHandler import log

from ..config.settings import (
	build_provider_config,
	set_openai_compat_config,
)
from ..providers.adapters.openai_compat import OpenAICompatProvider
from ..providers.litert_manager import LiteRTModelManager
from ..providers.litert_models import recommended_models
from ..providers.model_manager import (
	CloudModelManagerAdapter,
	ManagedModel,
	ModelManagerProvider,
	ModelState,
)
from .enabled_models import EnabledModelsStore

_RECOMMENDED_PRIORITY = 50


def _make_set_model(provider_id: str):
	"""Return a set_model_fn that updates model_name for the given provider.

	The config is rebuilt from the *provider's own* YAML keys so that
	switching the active model never clobbers the target provider's
	other settings (base URL, API key, etc.) with the active provider's
	values.
	"""

	def _set(model_id: str) -> None:
		cfg = build_provider_config(provider_id)
		set_openai_compat_config(
			type(cfg)(
				**{**vars(cfg), "provider": provider_id, "model_name": model_id},
			)
		)

	return _set


class ModelManagerDialog(wx.Dialog):
	"""Browse and manage models for a provider."""

	# TRANSLATORS: Title of the model manager dialog.
	_TITLE = "AI Assistant — Model Manager"

	def __init__(
		self,
		parent: wx.Window,
		provider: ModelManagerProvider,
	) -> None:
		super().__init__(
			parent,
			title=_(self._TITLE),
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
		)
		self._provider = provider
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

		# ── Provider combo box ───────────────────────────────────
		# TRANSLATORS: Label for the provider selector in the model manager.
		provider_label = wx.StaticText(self, label=_("Provider:"))
		s_helper.addItem(provider_label)

		self._provider_combo = wx.Choice(
			self,
			choices=self._provider_choices(),
		)
		self._provider_combo.SetSelection(0)
		self._provider_combo.Bind(
			wx.EVT_CHOICE,
			self._on_provider_change,
		)
		s_helper.addItem(self._provider_combo)
		s_helper.sizer.AddSpacer(8)

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
	# Provider management
	# ------------------------------------------------------------------

	@staticmethod
	def _discover_providers() -> dict[str, tuple[str, ModelManagerProvider]]:
		"""Return {display_name: (provider_id, ModelManagerProvider)} for all
		registered providers.
		"""
		result: dict[str, tuple[str, ModelManagerProvider]] = {}

		# ── LiteRT-LM (local) ───────────────────────────────────
		try:
			litert = LiteRTModelManager(config=build_provider_config("litert-lm"))
			# TRANSLATORS: Provider option in the model manager combo box.
			result[_("LiteRT-LM")] = ("litert-lm", litert)
		except Exception:
			log.exception("Unable to create LiteRT-LM model manager")

		# ── Gemini (cloud) ──────────────────────────────────────
		try:
			gemini_config = build_provider_config("gemini")
			if str(gemini_config.api_key or "").strip():
				gemini = CloudModelManagerAdapter(
					provider_id="gemini",
					config=gemini_config,
					provider_class=OpenAICompatProvider,
					set_model_fn=_make_set_model("gemini"),
					get_config_fn=lambda: build_provider_config("gemini"),
				)
				# TRANSLATORS: Provider option in the model manager combo box.
				result[_("Gemini")] = ("gemini", gemini)
		except Exception:
			pass

		# ── Ollama (local server) ───────────────────────────────
		try:
			ollama_config = build_provider_config("ollama")
			if str(ollama_config.base_url or "").strip():
				ollama = CloudModelManagerAdapter(
					provider_id="ollama",
					config=ollama_config,
					provider_class=OpenAICompatProvider,
					set_model_fn=_make_set_model("ollama"),
					get_config_fn=lambda: build_provider_config("ollama"),
				)
				# TRANSLATORS: Provider option in the model manager combo box.
				result[_("Ollama")] = ("ollama", ollama)
		except Exception:
			pass

		# ── OpenAI (cloud) ──────────────────────────────────────
		try:
			openai_config = build_provider_config("openai")
			if str(openai_config.api_key or "").strip():
				openai_adapter = CloudModelManagerAdapter(
					provider_id="openai",
					config=openai_config,
					provider_class=OpenAICompatProvider,
					set_model_fn=_make_set_model("openai"),
					get_config_fn=lambda: build_provider_config("openai"),
				)
				# TRANSLATORS: Provider option in the model manager combo box.
				result[_("OpenAI")] = ("openai", openai_adapter)
		except Exception:
			pass

		return result

	def _provider_choices(self) -> list[str]:
		# Lazy cache: built when the provider combo is first populated (wx
		# lifecycle), so it cannot be initialized in __init__.
		# pylint: disable=attribute-defined-outside-init
		self._provider_map = self._discover_providers()
		return list(self._provider_map.keys())

	def _on_provider_change(self, event: wx.CommandEvent) -> None:
		idx = self._provider_combo.GetSelection()
		if idx < 0:
			return
		label = self._provider_combo.GetString(idx)
		entry = self._provider_map.get(label)
		if entry is None:
			return
		_provider_id, provider = entry
		self._provider = provider
		if _provider_id == "litert-lm":
			self._known_map = {m.filename: m for m in recommended_models()}
		else:
			self._known_map = {}
		self._refresh_model_list()

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

	def _on_double_click(self, event: wx.ListEvent) -> None:
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

	def _on_show_disabled(self, event: wx.CommandEvent) -> None:
		self._refresh_model_list()

	def _on_download(self, event: wx.CommandEvent) -> None:
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
		model_id: str,
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

	def _on_delete(self, event: wx.CommandEvent) -> None:
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

	def _on_set_active(self, event: wx.CommandEvent) -> None:
		model = self._get_selected_model()
		if model is None or not model.state.is_ready():
			return
		self._provider.set_active_model(model.id)
		self._refresh_model_list()

	def _on_close(self, event: wx.Event) -> None:
		self.Destroy()

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


def open_model_manager(parent: wx.Window) -> None:
	"""Open the model manager dialog.

	The dialog discovers all configured providers (local and cloud)
	and presents them in a provider combo box.  Called from the Tools
	menu.  Uses NVDA's prePopup/postPopup pattern.
	"""
	# Start with LiteRT-LM as the default provider; the dialog's
	# _discover_providers() populates the combo with all available.
	provider = LiteRTModelManager(config=build_provider_config("litert-lm"))
	dlg = ModelManagerDialog(gui.mainFrame, provider)
	dlg.Show()
