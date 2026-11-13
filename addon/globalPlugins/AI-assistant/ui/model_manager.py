# -*- coding: utf-8 -*-
"""Model Manager dialog — browse, enable, download, and delete models.

Opened from the provider management dialog for a **specific provider**
(the provider is passed in; the dialog never asks the user to choose
one again).  Provides a model list grouped by priority and download
state, a details panel, and action buttons (download, delete, set
active, enable/disable) driven by the provider's model features.
"""

from __future__ import annotations

import wx

from gui import guiHelper

from ..providers.model_manager import (
	ManagedModel,
	ModelManagerProvider,
	ModelState,
	ModelAction, available_model_actions,
)
from ..providers.model_import import default_model_id_for_file, parse_model_import_source
from ..providers.registry import (
	build_model_manager,
	model_manager_title,
	provider_display_name,
)
from .download_progress import DownloadProgressDialog
from ..config.enabled_models import ModelVisibilityStore
from ..service.model_cache import model_capability_cache, model_catalog_cache
from ..service.error_reporter import ErrorContext, error_reporter
from .task_runner import TaskHandle, background_tasks
from ..core.cancellation import cancellation_event_scope
from . import nvda_ui

_RECOMMENDED_PRIORITY = 50


def import_file_wildcard(provider_id: str) -> str:
	"""Return the local model-file filter for a provider."""
	provider = str(provider_id or "").strip().lower()
	if provider == "litert-lm":
		return _("LiteRT-LM files (*.litertlm)|*.litertlm|All files (*.*)|*.*")
	if provider in {"llama-cpp", "llama-cpp-server"}:
		return _("GGUF files (*.gguf)|*.gguf|All files (*.*)|*.*")
	return _("Model files|*.gguf;*.litertlm;*.litert|All files (*.*)|*.*")


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
		self._enabled_store = ModelVisibilityStore()
		self._models: list[ManagedModel] = []
		self._displayed_models: list[ManagedModel] = []
		self._pending_downloads: set[str] = set()
		self._fetch_task: TaskHandle[list[ManagedModel]] | None = None
		self._mutation_task: TaskHandle[None] | None = None
		self._is_destroyed = False
		self._refresh_generation = 0
		self._refresh_pending = False
		self._mutation_focus = None

		self._build_ui()
		self._start_initial_load()

		# Escape closes the dialog.
		self.SetEscapeId(wx.ID_CLOSE)

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
		self._list.AppendColumn("", width=280)
		# TRANSLATORS: Column header for the download status.
		self._list.AppendColumn(_("Status"), width=180)
		# TRANSLATORS: Column header for the model file size.
		self._list.AppendColumn(_("Size"), width=100)

		self._list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_selection_change)
		self._list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self._on_selection_change)
		self._list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_double_click)
		self._list.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
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
		button_sizer = wx.WrapSizer(wx.HORIZONTAL)

		# TRANSLATORS: Button to download a model.
		self._download_btn = wx.Button(self, label=_("Download"))
		self._download_btn.Bind(wx.EVT_BUTTON, self._on_download)
		self._download_btn.Show(self._provider.features.download)
		button_sizer.Add(self._download_btn, flag=wx.RIGHT, border=5)

		# TRANSLATORS: Button to import a local model file.
		self._import_file_btn = wx.Button(self, label=_("Import file..."))
		self._import_file_btn.Bind(wx.EVT_BUTTON, self._on_import_file)
		button_sizer.Add(self._import_file_btn, flag=wx.RIGHT, border=5)
		# TRANSLATORS: Button to import a model from Hugging Face.
		self._import_hf_btn = wx.Button(self, label=_("Import from Hugging Face..."))
		self._import_hf_btn.Bind(wx.EVT_BUTTON, self._on_import_hugging_face)
		button_sizer.Add(self._import_hf_btn, flag=wx.RIGHT, border=5)

		self._import_preset_btn = wx.Button(self, label=_("Import preset..."))
		self._import_preset_btn.Bind(wx.EVT_BUTTON, self._on_import_preset)
		self._import_preset_btn.Show(self._provider.features.import_preset)
		button_sizer.Add(self._import_preset_btn, flag=wx.RIGHT, border=5)
		self._cache_delete_btn = wx.Button(self, label=_("Delete cached files..."))
		self._cache_delete_btn.Bind(wx.EVT_BUTTON, self._on_delete_cache)
		self._cache_delete_btn.Show(callable(getattr(type(self._provider), "delete_cached_files", None)))
		button_sizer.Add(self._cache_delete_btn, flag=wx.RIGHT, border=5)
		self._refresh_btn = wx.Button(self, label=_("Refresh"))
		self._refresh_btn.Bind(wx.EVT_BUTTON, self._on_refresh)
		button_sizer.Add(self._refresh_btn, flag=wx.RIGHT, border=5)

		# TRANSLATORS: Button to delete a downloaded model.
		self._delete_btn = wx.Button(self, label=_("Remove model") if self._provider.provider_id == "llama-cpp-server" else _("Delete"))
		self._delete_btn.Bind(wx.EVT_BUTTON, self._on_delete)
		button_sizer.Add(self._delete_btn, flag=wx.RIGHT, border=5)

		# TRANSLATORS: Button to set the selected model as active.
		self._set_active_btn = wx.Button(self, label=_("Set Active"))
		self._set_active_btn.Bind(wx.EVT_BUTTON, self._on_set_active)
		button_sizer.Add(self._set_active_btn)

		# TRANSLATORS: Button to open the per-model Configure dialog.
		self._configure_btn = wx.Button(self, label=_("Configure Model..."))
		self._configure_btn.Bind(wx.EVT_BUTTON, self._on_configure_model)
		button_sizer.Add(self._configure_btn, flag=wx.LEFT, border=5)
		self._runtime_btn = wx.Button(self, label=_("Runtime settings..."))
		self._runtime_btn.Bind(wx.EVT_BUTTON, self._on_runtime_settings)
		self._runtime_btn.Show(callable(getattr(type(self._provider), "get_runtime_options", None)))
		button_sizer.Add(self._runtime_btn, flag=wx.LEFT, border=5)

		s_helper.addItem(button_sizer)

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

	def _start_initial_load(self) -> None:
		"""Show a loading placeholder and start fetching models in the background.

		This prevents the dialog from freezing when the provider needs
		to make a network round-trip (e.g. Gemini /v1/models).
		"""
		self._list.DeleteAllItems()
		self._show_loading_indicator()
		self._update_buttons()
		self._request_model_refresh()

	def _on_models_fetched(self, models: list[ManagedModel], focus_model_id: str | None = None, *, generation: int | None = None) -> None:
		"""Populate the list with fetched models (called on the main thread)."""
		if self._is_destroyed or (generation is not None and generation != self._refresh_generation):
			return
		self._fetch_task = None
		self._populate_model_list(models, focus_model_id)

	def _on_models_fetch_error(self, error: Exception, *, generation: int | None = None) -> None:
		if self._is_destroyed or (generation is not None and generation != self._refresh_generation):
			return
		self._fetch_task = None
		error_reporter.report(
			error,
			ErrorContext(
				operation="model catalog refresh",
				provider=self._provider.provider_id,
				origin="model manager",
				optional=True,
			),
			owner=lambda presentation: wx.MessageBox(
				presentation.message,
				presentation.title,
				wx.ICON_ERROR,
				parent=self,
			),
		)
		# Keep the last known catalog; a failed refresh must not look like an
		# empty provider or cause the user to lose the current selection.
		if self._models:
			self._populate_model_list(self._models)
		else:
			self._list.DeleteAllItems()
			self._list.InsertItem(0, _("Unable to load models. Try again."))

		self._update_buttons()

	def _show_loading_indicator(self) -> None:
		"""Display a 'Loading models...' placeholder."""
		idx = self._list.InsertItem(0, _("Loading models..."))
		font = self._list.GetFont()
		font.Italic = True
		self._list.SetItemFont(idx, font)

	def _refresh_model_list(self, focus_model_id: str | None = None) -> None:
		"""Reload models from the provider and repopulate the list.

		If a background fetch is already in progress the call is a
		no-op — the UI will be repopulated when the fetch completes.
		"""
		if self._fetch_task is not None and not self._fetch_task.done:
			return

		# Save currently focused model ID before rebuilding.
		if focus_model_id is None:
			focused = self._get_selected_model()
			focus_model_id = focused.id if focused else None

		self._request_model_refresh(focus_model_id)

	def _request_model_refresh(self, focus_model_id: str | None = None) -> None:
		"""Fetch provider models off the wx thread."""
		if self._mutation_task is not None:
			self._refresh_pending = True
			return
		if self._fetch_task is not None and not self._fetch_task.done:
			return
		if not self._models:
			self._list.DeleteAllItems()
			self._show_loading_indicator()
		self._update_buttons()
		self._refresh_generation += 1
		generation = self._refresh_generation
		self._fetch_task = background_tasks.submit(
			lambda _cancel: list(self._provider.list_managed_models()),
			on_success=lambda models: self._on_models_fetched(models, focus_model_id, generation=generation),
			on_error=lambda error: self._on_models_fetch_error(error, generation=generation),
			is_alive=lambda: not self._is_destroyed,
		)

	def _populate_model_list(
		self,
		models: list[ManagedModel],
		focus_model_id: str | None = None,
	) -> None:
		"""Populate the list control from *models* (must be called on main thread)."""
		self._models = models
		# Filter using visibility store
		disabled_ids = self._enabled_store.get_disabled_models(self._provider.provider_id)

		# Separate by download state + priority
		recommended_ready: list[ManagedModel] = []
		recommended_download: list[ManagedModel] = []
		other_ready: list[ManagedModel] = []
		other_download: list[ManagedModel] = []

		show_disabled = self._show_disabled_cb.GetValue()

		for m in self._models:
			if not show_disabled and m.id in disabled_ids:
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
			self._add_models(recommended_ready, disabled_ids)
		if recommended_download:
			self._add_section_header(_("── Recommended — Available to download ──") if self._provider.features.download else _("── Recommended — Unavailable sources ──"))
			self._add_models(recommended_download, disabled_ids)
		if other_ready:
			self._add_section_header(_("── Other Models — Ready to use ──"))
			self._add_models(other_ready, disabled_ids)
		if other_download:
			self._add_section_header(_("── Other Models — Available to download ──") if self._provider.features.download else _("── Other Models — Unavailable sources ──"))
			self._add_models(other_download, disabled_ids)

		# Restore focus to the previously selected model.
		if focus_model_id is not None:
			self._select_displayed_model(focus_model_id)

		self._update_buttons()

	def _select_displayed_model(self, model_id: str) -> None:
		"""Find *model_id* in displayed models and select its row."""
		count = self._list.GetItemCount()
		model_idx = 0
		for i in range(count):
			if self._list.GetItemText(i, 3):  # has status → real model
				if model_idx < len(self._displayed_models) and self._displayed_models[model_idx].id == model_id:
					self._list.Select(i, on=True)
					self._list.Focus(i)
					return
				model_idx += 1

	def _add_section_header(self, label: str) -> None:
		idx = self._list.InsertItem(self._list.GetItemCount(), label)
		font = self._list.GetFont()
		font.SetWeight(wx.FONTWEIGHT_BOLD)
		self._list.SetItemFont(idx, font)
		self._list.SetItemBackgroundColour(idx, wx.Colour(230, 230, 240))

	def _add_models(
		self,
		models: list[ManagedModel],
		disabled_ids: set[str],
	) -> None:
		for m in models:
			idx = self._list.InsertItem(self._list.GetItemCount(), "")

			# Column 0: enabled checkbox
			is_enabled = m.id not in disabled_ids
			self._list.SetItem(idx, 0, "☑" if is_enabled else "☐")  # noqa: RUF001

			# Column 1: active marker
			is_active = _model_matches_active(m, self._active_id_clean)
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

	def _get_displayed_model_at(self, list_idx: int) -> ManagedModel | None:
		"""Map a list-control index to the displayed model, skipping section headers."""
		count = self._list.GetItemCount()
		model_idx = 0
		for i in range(count):
			if i == list_idx:
				if model_idx < len(self._displayed_models):
					if self._list.GetItemText(i, 3):  # has status → real model
						return self._displayed_models[model_idx]
				return None
			if self._list.GetItemText(i, 3):  # has a status → real model
				model_idx += 1
		return None

	def _get_selected_model(self) -> ManagedModel | None:
		"""Return the currently selected model, skipping section headers."""
		sel = self._list.GetFirstSelected()
		if sel < 0:
			return None
		return self._get_displayed_model_at(sel)

	def _update_buttons(self) -> None:
		busy = self._mutation_task is not None
		features = self._provider.features
		self._import_file_btn.Enable(not busy and features.import_model)
		self._import_hf_btn.Enable(not busy and features.import_model)
		self._import_preset_btn.Enable(not busy and features.import_preset)
		if hasattr(self, "_refresh_btn"):
			self._refresh_btn.Enable(not busy and self._fetch_task is None)
		model = self._get_selected_model()
		actions = available_model_actions(model, features) if model is not None else frozenset()
		self._download_btn.Enable(not busy and ModelAction.DOWNLOAD in actions and model.id not in self._pending_downloads)
		self._delete_btn.Enable(not busy and ModelAction.REMOVE in actions)
		self._cache_delete_btn.Enable(not busy and ModelAction.DELETE_CACHE in actions)
		self._set_active_btn.Enable(not busy and ModelAction.SELECT in actions)
		self._configure_btn.Enable(not busy and model is not None)
		self._runtime_btn.Enable(not busy and model is not None and model.registered)

	def _update_details(self) -> None:
		model = self._get_selected_model()
		if model is None:
			self._details_text.SetValue("")
			return

		desc = model.description
		caps = _capabilities_label(model)
		lines = [
			model.display_name,
			"",
			_("Size: {size}").format(size=model.size_hint),
			_("Status: {status}").format(status=_status_label(model.state)),
			_("Capabilities: {capabilities}").format(capabilities=caps),
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

	def _on_left_down(self, event: wx.MouseEvent) -> None:
		"""Single-click on the checkbox column (col 0) toggles enabled."""
		x_pos = event.GetPosition().x
		col0_width = self._list.GetColumnWidth(0)
		if x_pos <= col0_width:
			idx = self._list.HitTest(event.GetPosition())[0]
			if idx >= 0:
				model = self._get_displayed_model_at(idx)
				if model is not None:
					is_enabled = self._enabled_store.is_model_visible(
						self._provider.provider_id,
						model.id,
					)
					self._toggle_enabled(model, not is_enabled)
					return  # handled; skip normal selection processing
		event.Skip()

	def _on_double_click(self, _event: wx.ListEvent) -> None:
		"""Double-click / Enter: toggle enabled."""
		model = self._get_selected_model()
		if model is None:
			return
		is_enabled = self._enabled_store.is_model_visible(
			self._provider.provider_id,
			model.id,
		)
		self._toggle_enabled(model, not is_enabled)

	def _on_show_disabled(self, _event: wx.CommandEvent) -> None:
		self._refresh_model_list()

	def _on_download(self, _event: wx.CommandEvent) -> None:
		model = self._get_selected_model()
		if model is None:
			return
		model_id = model.id
		self._pending_downloads.add(model_id)
		self._update_buttons()

		def worker(dlg: DownloadProgressDialog) -> None:
			def progress(msg: str, downloaded: int | None, total: int | None) -> None:
				dlg.update_message(msg)
				if downloaded is not None and total is not None:
					dlg.update_progress(downloaded, total)

			self._provider.download_model(
				model_id,
				on_progress=progress,
				cancel_event=dlg.cancel_event,
			)
			dlg.signal_complete(
				True,
				# TRANSLATORS: Success message after model download.
				_("{name} downloaded successfully.").format(name=model.display_name),
			)

		def on_done() -> None:
			model_catalog_cache.invalidate(self._provider.provider_id)
			model_capability_cache.invalidate(self._provider.provider_id)
			self._pending_downloads.discard(model_id)
			self._refresh_model_list()

		DownloadProgressDialog.run(
			self,
			title=_("Downloading Model"),
			worker=worker,
			on_complete=on_done,
			initial_message=_("Downloading {}...").format(model.display_name),
		)

	def _on_refresh(self, _event: wx.Event) -> None:
		model_catalog_cache.invalidate(self._provider.provider_id)
		self._refresh_model_list()

	def _on_import_preset(self, _event: wx.Event) -> None:
		if not self._provider.features.import_preset:
			return
		dialog = wx.FileDialog(self, message=_("Select llama.cpp model preset"),
			wildcard=_("Preset files (*.ini)|*.ini|All files (*.*)|*.*"), style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
		try:
			if dialog.ShowModal() != wx.ID_OK:
				return
			path = dialog.GetPath()
		finally:
			dialog.Destroy()
		def describe(summary):
			if self._is_destroyed:
				return
			message = _("Imported {count} models and {settings} runtime settings. The original file is unchanged and is no longer watched.\n\nModels:\n{models}").format(count=len(summary.model_ids), settings=summary.option_count, models="\n".join(summary.model_ids))
			wx.MessageBox(message, _("Preset import summary"), wx.OK | wx.ICON_INFORMATION, parent=self)
		self._run_mutation(lambda: self._provider.import_preset(path), _("Preset imported into the model catalog."), on_success=describe)

	def _on_delete(self, _event: wx.CommandEvent) -> None:
		model = self._get_selected_model()
		if model is None or ModelAction.REMOVE not in available_model_actions(model, self._provider.features):
			return
		managed_reference = model.actions is not None
		message = (_("Remove {model}? Original files and the shared llama.cpp cache will be kept. Any add-on-owned llama.cpp server will be stopped.")
			if managed_reference else _("Delete downloaded model {model}?"))
		if wx.MessageBox(message.format(model=model.display_name), _("Remove model") if managed_reference else _("Delete model"), wx.YES_NO | wx.ICON_QUESTION, parent=self) != wx.YES:
			return
		was_active = _model_matches_active(model, self._provider.active_model_id)
		remaining = [item.id for item in self._displayed_models if item.id != model.id]
		focus = remaining[0] if remaining else None
		feedback = (_("Model removed. Select another model before making a request.") if was_active else _("Model removed.")) if managed_reference else _("Model deleted.")
		self._run_mutation(lambda: self._provider.delete_model(model.id), feedback, focus_model_id=focus)

	def _on_delete_cache(self, _event: wx.Event) -> None:
		model = self._get_selected_model()
		if model is None or ModelAction.DELETE_CACHE not in available_model_actions(model, self._provider.features):
			return
		message = _("Delete the add-on-owned cached files for {model}? The model registration will remain. Any add-on-owned llama.cpp server will be stopped.\n\nFiles:\n{files}").format(model=model.display_name, files="\n".join(model.cached_files))
		if wx.MessageBox(message, _("Delete cached files"), wx.YES_NO | wx.ICON_WARNING, parent=self) != wx.YES:
			return
		self._run_mutation(lambda: self._provider.delete_cached_files(model.id), _("Cached model files deleted."), focus_model_id=model.id)

	def _run_mutation(self, operation, feedback: str, *, focus_model_id: str | None = None, on_success=None) -> None:
		if self._mutation_task is not None or self._is_destroyed:
			return
		self._refresh_generation += 1
		if self._fetch_task is not None:
			self._fetch_task.cancel()
			self._fetch_task = None
		self._mutation_focus = focus_model_id
		def work(cancel):
			with cancellation_event_scope(cancel):
				return operation()
		def completed(result):
			if feedback:
				nvda_ui.queue(nvda_ui.message, feedback)
			if on_success:
				wx.CallAfter(on_success, result)
		self._mutation_task = background_tasks.submit(work,
			on_success=completed,
			on_error=lambda error: error_reporter.report(error,
				ErrorContext(operation="manage model", provider=self._provider.provider_id, origin="model manager"),
				owner=lambda presentation: wx.MessageBox(presentation.message, presentation.title, wx.ICON_ERROR, parent=self)),
			on_finally=self._finish_mutation, is_alive=lambda: not self._is_destroyed)
		self._update_buttons()

	def _finish_mutation(self) -> None:
		self._mutation_task = None
		self._refresh_pending = False
		model_catalog_cache.invalidate(self._provider.provider_id)
		model_capability_cache.invalidate(self._provider.provider_id)
		if not self._is_destroyed:
			self._refresh_model_list(self._mutation_focus)
			self._list.SetFocus()

	def _prompt_model_id(self, default: str | None = None) -> tuple[bool, str | None]:
		model_id_dialog = wx.TextEntryDialog(
			self,
			_("Runtime model ID:"),
			_("Import Model"),
		)
		try:
			if default:
				model_id_dialog.SetValue(default)
			if model_id_dialog.ShowModal() != wx.ID_OK:
				return False, None
			return True, model_id_dialog.GetValue().strip() or None
		finally:
			model_id_dialog.Destroy()

	def _run_import(self, source: str, model_id: str | None) -> None:
		try:
			request = parse_model_import_source(source, model_id, self._provider.provider_id)
		except ValueError as exc:
			error_reporter.report(
				exc,
				ErrorContext(
					operation="validate model import",
					provider=self._provider.provider_id,
					origin="model manager",
				),
				owner=lambda presentation: wx.MessageBox(
					presentation.message,
					_("Invalid model source"),
					wx.ICON_ERROR,
					parent=self,
				),
			)
			return

		def worker(dlg: DownloadProgressDialog) -> None:
			def progress(msg: str, downloaded: int | None, total: int | None) -> None:
				dlg.update_message(msg)
				if downloaded is not None and total is not None:
					dlg.update_progress(downloaded, total)

			self._provider.import_model(request, progress, dlg.cancel_event)
			dlg.signal_complete(True, _("Model imported successfully."))

		DownloadProgressDialog.run(
			self,
			title=_("Importing Model"),
			worker=worker,
			on_complete=self._refresh_model_list,
			initial_message=_("Importing model..."),
		)

	def _on_import_file(self, _event: wx.CommandEvent) -> None:
		if not self._provider.features.import_model:
			return
		file_dialog = wx.FileDialog(
			self,
			message=_("Select model file"),
			wildcard=import_file_wildcard(self._provider.provider_id),
			style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
		)
		try:
			if file_dialog.ShowModal() != wx.ID_OK:
				return
			source = file_dialog.GetPath()
		finally:
			file_dialog.Destroy()
		confirmed, model_id = self._prompt_model_id(default_model_id_for_file(source))
		if not confirmed:
			return
		self._run_import(source, model_id)

	def _on_import_hugging_face(self, _event: wx.CommandEvent) -> None:
		if not self._provider.features.import_model:
			return
		source_dialog = wx.TextEntryDialog(
			self,
			_("Enter a Hugging Face repository reference (use repo:quantization for llama.cpp):"),
			_("Import from Hugging Face"),
		)
		try:
			if source_dialog.ShowModal() != wx.ID_OK:
				return
			source = source_dialog.GetValue().strip()
		finally:
			source_dialog.Destroy()
		if not source:
			return
		confirmed, model_id = self._prompt_model_id()
		if confirmed:
			self._run_import(source, model_id)

	def _on_set_active(self, _event: wx.CommandEvent) -> None:
		model = self._get_selected_model()
		if model is None or not model.state.is_ready():
			return
		self._run_mutation(lambda: self._provider.set_active_model(model.id), _("Active model changed."), focus_model_id=model.id)

	def _on_runtime_settings(self, _event):
		model = self._get_selected_model()
		if model is None or not model.registered:
			return
		def show(configuration):
			if self._is_destroyed:
				return
			from .llama_runtime_dialog import LlamaRuntimeDialog
			options, supported = configuration
			dialog = LlamaRuntimeDialog(self, model.id, options, supported)
			try:
				if dialog.ShowModal() != wx.ID_OK:
					return
				updated = dialog.options
			finally:
				dialog.Destroy()
			self._run_mutation(lambda: self._provider.set_runtime_options(model.id, updated),
				_("Runtime settings saved. They apply on the next model load; the owned server may restart."), focus_model_id=model.id)
		self._run_mutation(lambda: self._provider.get_runtime_configuration(model.id), "", on_success=show)

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
		self._is_destroyed = True
		if self._fetch_task is not None:
			self._fetch_task.cancel()
		if self._mutation_task is not None:
			self._mutation_task.cancel()
		self.EndModal(wx.ID_CANCEL)

	# ------------------------------------------------------------------
	# Helpers
	# ------------------------------------------------------------------

	def _toggle_enabled(self, model: ManagedModel, enabled: bool) -> None:
		self._enabled_store.set_model_visible(
			self._provider.provider_id,
			model.id,
			enabled,
		)
		self._refresh_model_list(focus_model_id=model.id)


# ── Module-level helpers ───────────────────────────────────────────


def _status_label(state: ModelState) -> str:
	"""Return a human-readable label for a model state."""
	if state == ModelState.REGISTERED:
		return _("Registered — loads on first use")
	if state == ModelState.DOWNLOADED:
		return _("Downloaded")  # noqa: RUF001
	if state == ModelState.NOT_DOWNLOADED:
		return _("Not downloaded or source missing")  # noqa: RUF001
	if state == ModelState.DOWNLOADING:
		return _("Downloading...")  # noqa: RUF001
	if state == ModelState.FAILED:
		return _("Failed")  # noqa: RUF001
	if state == ModelState.READY:
		return _("Available")
	return str(state.value)


def _model_matches_active(model: ManagedModel, active_id: str | None) -> bool:
	"""Check if *model* matches the active model.

	Checks both ``model.id`` and ``model.canonical_id`` (for variant
	entries whose display ID is a filename but whose parent model is
	the canonical repo ID).  Performs loose normalized comparison as
	a fallback.
	"""
	if active_id is None:
		return False
	if model.actions is not None:
		return model.id == active_id.strip()
	ids_to_check = [model.id]
	if model.canonical_id and model.canonical_id not in ids_to_check:
		ids_to_check.append(model.canonical_id)
	active = active_id.strip().lower()
	for mid in ids_to_check:
		norm = mid.strip().lower()
		if (
			norm == active
			or norm.replace("-", "_") == active.replace("-", "_")
			or norm.replace("-", "") == active.replace("-", "")
		):
			return True
	return False


def _capabilities_label(model: ManagedModel) -> str:
	"""Return a human-readable capabilities string."""
	parts: list[str] = []
	caps = set(model.capabilities)
	if "streaming" in caps:
		parts.append(_("Streaming"))
	if "vision" in caps or "image_input" in caps:
		parts.append(_("Vision"))
	if "chat" in caps:
		parts.append(_("Chat"))
	if "completion" in caps:
		parts.append(_("Completion"))
	if "tools" in caps:
		parts.append(_("Tools"))
	return ", ".join(parts) if parts else _("Text")


def open_model_manager(parent: wx.Window, provider_id: str) -> None:
	"""Open the model manager dialog for *provider_id*.

	The provider context is already known — the dialog manages that
	provider's models and never asks the user to choose a provider
	again.  Modal: returns when the dialog is closed.
	"""
	provider = build_model_manager(
		provider_id,
		model_cache=model_catalog_cache,
		capability_cache=model_capability_cache,
	)
	if provider.features.configuration_management:
		from .llama_model_manager import LlamaModelsDialog
		dlg = LlamaModelsDialog(parent, provider)
	else:
		dlg = ModelManagerDialog(parent, provider, provider_display_name(provider_id))
	try:
		dlg.ShowModal()
	finally:
		dlg.Destroy()
