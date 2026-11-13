"""Accessible llama model management consuming explicit application policy."""
import time
import wx
from gui import guiHelper

from ..core.translation import _
from ..core.cancellation import cancellation_event_scope
from ..providers.model_manager import ModelAction
from ..providers.llama_catalog import files_label, runtime_label, cache_source_label
from ..config.enabled_models import ModelVisibilityStore
from ..service.error_reporter import ErrorContext, error_reporter
from .task_runner import background_tasks


def filter_entries(entries, kind, search):
	query = search.strip().casefold()
	return [entry for entry in entries if (entry.kind == kind if kind else entry.kind != "downloaded") and
		(query in entry.model.display_name.casefold() or query in entry.model.id.casefold()
		 or (entry.asset and query in entry.asset.path.casefold()))]


def primary_action(entry):
	if entry is None:
		return None
	actions = entry.model.actions or ()
	if ModelAction.CREATE_CONFIGURATION in actions:
		return "create"
	if ModelAction.SELECT in actions:
		return "use"
	if ModelAction.LOCATE_SOURCE in actions:
		return "locate"
	return None


class LlamaModelsDialog(wx.Dialog):
	def __init__(self, parent, provider):
		super().__init__(parent, title=_("llama.cpp model configurations"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self._provider = provider
		self._entries, self._rows = [], []
		self._task = None
		self._closed = False
		self._generation = 0
		self._completed_generation = -1
		self._visibility = ModelVisibilityStore()
		self._draft = {}
		self._edit_drafts = {}
		self._roots = None
		self._mutation = False
		self._last_stage_announcement = 0
		self._build()
		self._unsubscribe = self._provider.model_operations.subscribe(self._operation_changed)
		self.refresh()

	def _build(self):
		helper = guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)
		self._search = helper.addLabeledControl(_("Search models:"), wx.TextCtrl)
		self._search.Bind(wx.EVT_TEXT, lambda event: self._render())
		self._list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
		for name, width in ((_("Name"), 240), (_("Selected"), 80), (_("Files / source"), 190), (_("Runtime"), 180)):
			self._list.AppendColumn(name, width=width)
		self._list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda event: self._selection_changed())
		self._list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda event: self._primary_action())
		helper.addItem(self._list, flag=wx.EXPAND, proportion=1)
		self._details = helper.addLabeledControl(_("Highlighted model details:"), wx.TextCtrl, style=wx.TE_READONLY | wx.TE_MULTILINE, size=(-1, 110))
		self._visible = wx.CheckBox(self, label=_("Show this configuration in the model selector"))
		self._visible.Bind(wx.EVT_CHECKBOX, self._visibility_changed)
		helper.addItem(self._visible)
		self._status = wx.StaticText(self, label=_("Loading configurations..."))
		helper.addItem(self._status)
		buttons = wx.WrapSizer(wx.HORIZONTAL)
		self._buttons = {}
		for key, label, handler in (
			("primary", _("Select"), lambda event: self._primary_action()),
			("add", _("Add model..."), lambda event: self._create()),
			("lifecycle", _("Load"), self._lifecycle),
			("settings", _("Settings..."), self._settings),
			("more", _("More..."), self._more),
			("tasks", _("Tasks..."), self._tasks),
			("refresh", _("Refresh"), lambda event: self.refresh())):
			button = wx.Button(self, label=label)
			button.Bind(wx.EVT_BUTTON, handler)
			buttons.Add(button, 0, wx.ALL, 3)
			self._buttons[key] = button
		helper.addItem(buttons)
		close = wx.Button(self, wx.ID_CANCEL, _("Close"))
		close.Bind(wx.EVT_BUTTON, self._close)
		helper.addItem(close)
		self.Bind(wx.EVT_CLOSE, self._close)
		self.SetEscapeId(wx.ID_CANCEL)
		self.SetSizer(helper.sizer)
		self.SetSize((800, 670))
		self._search.SetFocus()
		self._update_buttons()

	def _selected(self):
		index = self._list.GetFirstSelected()
		return self._rows[index] if 0 <= index < len(self._rows) else None

	def _render(self, selected_id=None):
		if self._closed:
			return
		previous = self._selected()
		selected_id = selected_id or (previous.model.id if previous else None)
		top = self._list.GetTopItem()
		self._rows = filter_entries(self._entries, None, self._search.GetValue())
		self._list.Freeze()
		try:
			self._list.DeleteAllItems()
			for entry in self._rows:
				model = entry.model
				index = self._list.InsertItem(self._list.GetItemCount(), model.display_name)
				self._list.SetItem(index, 1, _("Yes") if entry.kind != "downloaded" and model.id == self._provider.active_model_id else _("No"))
				self._list.SetItem(index, 2, cache_source_label(entry.asset.source) if entry.kind == "downloaded" else files_label(model.file_availability))
				self._list.SetItem(index, 3, str(len(entry.configuration_ids)) if entry.kind == "downloaded" else runtime_label(entry.runtime))
				if model.id == selected_id:
					self._list.Select(index)
					self._list.Focus(index)
			if self._rows and 0 <= top < len(self._rows):
				self._list.EnsureVisible(top)
		finally:
			self._list.Thaw()
		self._selection_changed()

	def _selection_changed(self):
		entry = self._selected()
		if entry:
			model = entry.model
			lines = [model.display_name, _("ID: {id}").format(id=model.id), files_label(model.file_availability),
				runtime_label(entry.runtime), model.description, _("Selected for requests: {selected}").format(selected=_("Yes") if model.id == self._provider.active_model_id else _("No"))]
			if entry.source_reference:
				lines.append(_("Source: {source}").format(source=entry.source_reference))
			if entry.runtime_options:
				lines.append(_("Saved runtime settings: {settings}").format(settings="; ".join(f"{key} = {value}" for key, value in entry.runtime_options)))
			capabilities = []
			for capability, label in (("chat", _("Chat")), ("image_input", _("Images")), ("audio_input", _("Audio input")), ("thinking", _("Reasoning"))):
				if capability in model.capabilities:
					capabilities.append(label)
			lines.append(_("Capabilities: {capabilities}").format(capabilities=", ".join(capabilities) or _("Unknown")))
			if entry.asset:
				lines.extend([entry.asset.path, _("Size: {size} bytes").format(size=entry.asset.size_bytes or 0),
					_("Repository: {repository}").format(repository=entry.asset.repository or _("Unknown")),
					_("Revision: {revision}").format(revision=entry.asset.revision or _("Unknown")),
					_("Quantization: {quantization}").format(quantization=entry.asset.quantization or _("Unknown")),
					_("Configurations using these files: {names}").format(names=", ".join(entry.configuration_ids) or _("None"))])
			for companion in getattr(entry, "companions", ()):
				role = {"vision": _("Vision projector"), "draft": _("Speculative draft"), "mtp": _("MTP model")}.get(companion.get("role"), _("Companion"))
				lines.append(_("{role}: {source}; artifact: {artifact}; compatibility: {compatibility}").format(role=role, source=companion.get("local_path") or companion.get("source", ""), artifact=companion.get("artifact") or _("Local file"), compatibility=_("Verified by successful load") if entry.runtime == "loaded" and companion.get("compatibility") == "verified" else _("Unverified until successful load")))
			if model.cached_files:
				lines.append(_("File dependencies (deletion is checked for other configurations): {files}").format(files="; ".join(model.cached_files)))
			self._details.SetValue("\n".join(lines))
			self._visible.SetValue(self._visibility.is_model_visible(self._provider.provider_id, model.id))
		else:
			self._details.SetValue("")
		self._update_buttons()

	def _update_buttons(self):
		entry = self._selected()
		busy = self._task is not None
		for button in self._buttons.values():
			button.Enable(not busy)
		primary = primary_action(entry)
		self._buttons["primary"].SetLabel({"create": _("Create configuration..."), "locate": _("Locate files..."), "use": _("Select")}.get(primary, _("Use")))
		self._buttons["primary"].Enable(not busy and primary is not None)
		registered = bool(entry and entry.model.registered)
		operation = self._operation(entry)
		self._buttons["lifecycle"].SetLabel(_("Stop") if operation else (_("Unload") if entry and entry.runtime == "loaded" else _("Load")))
		self._buttons["lifecycle"].Enable(registered and (operation is not None or not busy))
		self._buttons["settings"].Enable(not busy and registered and not operation)
		self._buttons["add"].Enable(not busy and not self._provider.model_operations.active())
		self._buttons["more"].Enable(not busy)

		self._visible.Enable(not busy and bool(entry and entry.kind != "downloaded"))

	def _speak(self, text):
		from . import nvda_ui
		nvda_ui.queue(nvda_ui.message, text)

	def _submit(self, work, *, mutation=False, feedback="", success=None):
		if self._closed or self._task is not None:
			return
		self._generation += 1
		generation = self._generation
		self._mutation = mutation
		def execute(cancel):
			with cancellation_event_scope(cancel):
				return work(cancel)
		def completed(result):
			if self._closed or generation != self._generation:
				return
			self._completed_generation = generation
			self._task = None
			if feedback:
				self._status.SetLabel(feedback)
				self._speak(feedback)
			if mutation:
				if isinstance(result, str):
					self._search.SetValue("")
				self.refresh(selected_id=result if isinstance(result, str) else None,
					after=(lambda: success(result)) if success else None)
			elif success:
				wx.CallAfter(lambda: success(result) if not self._closed and generation == self._generation else None)
		def failed(error):
			if self._closed or generation != self._generation:
				return
			self._completed_generation = generation
			self._status.SetLabel(_("Operation failed. Previous results are retained; refresh or edit the configuration to retry."))
			error_reporter.report(error, ErrorContext(operation="llama model management", provider=self._provider.provider_id, origin="model manager"),
				owner=lambda presentation: wx.MessageBox(presentation.message, presentation.title, wx.OK | wx.ICON_ERROR, parent=self))
		def finished():
			if self._closed or generation != self._generation:
				return
			if self._completed_generation != generation:
				message = _("Stop requested. Refreshing configuration state.") if mutation else _("Operation stopped.")
				self._status.SetLabel(message)
				self._speak(message)
			self._task = None
			self._update_buttons()
			if mutation and self._completed_generation != generation:
				self.refresh()
		self._task = background_tasks.submit(execute, on_success=completed, on_error=failed, on_finally=finished,
			is_alive=lambda: not self._closed)
		self._update_buttons()

	def refresh(self, selected_id=None, after=None):
		kind = None
		selected = self._selected()
		selected_id = selected_id or (selected.model.id if selected else None)
		message = _("Scanning downloaded models...") if kind == "downloaded" else _("Refreshing models...")
		self._status.SetLabel(message)
		if kind == "downloaded":
			self._speak(message)
		def fetch(cancel):
			snapshot = self._provider.discover_assets(self._roots) if kind == "downloaded" else None
			entries = self._provider.list_model_entries()
			return entries, snapshot, self._provider.server_models_error
		def show(result):
			self._entries, snapshot, server_error = result
			self._render(selected_id)
			count = len(self._rows)
			if server_error and kind != "downloaded":
				message = _("Server refresh failed. Previous server results are retained but unavailable for selection. Refresh to retry. {details}").format(details=server_error)
			elif snapshot and snapshot.errors:
				message = _("Found {count} models. Some cache folders could not be scanned: {errors}").format(count=count, errors="; ".join(snapshot.errors.values()))
			elif not count:
				message = _("No configurations. Use Add model to link a local file, Hugging Face reference or existing download.")
			else:
				message = _("{count} models shown.").format(count=count)
			self._status.SetLabel(message)
			self._speak(message)
			if after:
				after()
		self._submit(fetch, success=show)
		if kind == "downloaded":
			generation = self._generation
			def still_scanning():
				if not self._closed and generation == self._generation and self._task is not None:
					self._speak(_("Still scanning downloaded models. Use Stop operation to cancel."))
			wx.CallLater(3000, still_scanning)

	def _primary_action(self):
		# List activation remains available for reading during a task, unlike
		# disabled action buttons. Do not open a second modal or lose its draft.
		if self._closed or self._task is not None:
			return
		entry = self._selected()
		action = primary_action(entry)
		if action == "create":
			self._create(entry.asset)
		elif action == "locate":
			self._locate(None)
		elif action == "use":
			self._submit(lambda cancel: self._provider.set_active_model(entry.model.id), mutation=True,
				feedback=_("Model selected. The next request uses this model."))

	def _create(self, asset=None):
		from .llama_configuration_dialog import LlamaConfigurationDialog
		dialog = LlamaConfigurationDialog(self, asset=asset, initial=self._draft, provider=self._provider)
		try:
			if dialog.ShowModal() != wx.ID_OK:
				return
			values = dialog.values
			asset = dialog._asset
			self._draft = values
		finally:
			dialog.Destroy()
		def create(cancel):
			if values.get("asset_token") or asset:
				return self._provider.create_configuration_from_asset(values.get("asset_token") or asset.token, values["id"], values["name"], {}, select=values["select"], companions=values.get("companions", []))
			return self._provider.create_configuration(values["source"], values["id"], values["name"], select=values["select"], companions=values.get("companions", []))
		self._submit(create, mutation=True, feedback=_("Configuration created. No model files were copied or downloaded."),
			success=lambda identity: self._created(identity, values["edit"]))

	def _created(self, identity, edit):
		self._search.SetValue("")
		self._render(identity)
		if edit:
			self._runtime(None, identity=identity)

	def _runtime(self, event, identity=None):
		entry = self._selected()
		identity = identity or (entry.model.id if entry else None)
		if not identity:
			return
		def show(result):
			from .llama_runtime_dialog import LlamaRuntimeDialog
			options, supported = result
			dialog = LlamaRuntimeDialog(self, identity, options, supported, provider_context=self._provider.default_context)
			try:
				if dialog.ShowModal() != wx.ID_OK:
					return
				updated = dialog.options
			finally:
				dialog.Destroy()
			self._submit(lambda cancel: self._provider.set_runtime_options(identity, updated), mutation=True,
				feedback=_("Runtime settings saved. Changes apply on the next load; the owned server may restart."))
		self._submit(lambda cancel: self._provider.get_runtime_configuration(identity), success=show)

	def _generation_settings(self, event):
		entry = self._selected()
		if entry:
			from .model_config_dialog import open_model_configure
			from ..config.model_config import SEED_FIELD
			open_model_configure(self, self._provider.provider_id, entry.model.id, entry.model.display_name,
				field_labels={"num_ctx": _("Request context budget (tokens):")}, extra_fields=(SEED_FIELD,))

	def _duplicate(self, event):
		entry = self._selected()
		if not entry:
			return
		dialog = wx.TextEntryDialog(self, _("Name for the new configuration:"), _("Duplicate configuration"))
		try:
			if dialog.ShowModal() != wx.ID_OK:
				return
			name = dialog.GetValue().strip()
		finally:
			dialog.Destroy()
		from .llama_configuration_dialog import configuration_id
		self._submit(lambda cancel: self._provider.duplicate_configuration(entry.model.id, configuration_id(name), name),
			mutation=True, feedback=_("Configuration duplicated. Model files are shared."))

	def _locate(self, event):
		entry = self._selected()
		if not entry:
			return
		dialog = wx.FileDialog(self, message=_("Locate model file"), wildcard=_("GGUF files (*.gguf)|*.gguf"), style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
		try:
			if dialog.ShowModal() != wx.ID_OK:
				return
			path = dialog.GetPath()
		finally:
			dialog.Destroy()
		self._submit(lambda cancel: self._provider.relocate_configuration(entry.model.id, path), mutation=True,
			feedback=_("Model source updated. Existing settings were preserved."))

	def _remove(self, event):
		entry = self._selected()
		if entry and wx.MessageBox(_("Remove configuration {name}? Model files and other configurations will be kept. The owned server may stop.").format(name=entry.model.display_name),
			_("Remove configuration"), wx.YES_NO | wx.ICON_QUESTION, parent=self) == wx.YES:
			self._submit(lambda cancel: self._provider.delete_model(entry.model.id), mutation=True, feedback=_("Configuration removed. Model files were kept."))

	def _import_preset(self, event):
		dialog = wx.FileDialog(self, message=_("Import preset once"), wildcard=_("Preset files (*.ini)|*.ini"), style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
		try:
			if dialog.ShowModal() != wx.ID_OK:
				return
			path = dialog.GetPath()
		finally:
			dialog.Destroy()
		def previewed(preview):
			if preview.unsupported:
				wx.MessageBox(_("Import blocked. Unsupported options:\n{options}\n\nEdit a copy of the file and try again. The original and catalog are unchanged.").format(options="\n".join(preview.unsupported)),
					_("Preset import preview"), wx.OK | wx.ICON_WARNING, parent=self)
				return
			message = _("Import these configurations:\n{models}\n\nExisting IDs to replace:\n{replacements}\n\nThe original preset remains unchanged and will not be watched.").format(
				models="\n".join(record.model_id for record in preview.records), replacements="\n".join(preview.replace_ids) or _("None"))
			if wx.MessageBox(message, _("Confirm preset import"), wx.YES_NO | wx.ICON_QUESTION, parent=self) == wx.YES:
				self._submit(lambda cancel: self._provider.commit_preset_import(preview, replace_ids=preview.replace_ids), mutation=True,
					feedback=_("Preset configurations imported. The original file was kept."))
		self._submit(lambda cancel: self._provider.preview_preset_import(path), success=previewed)

	def _delete_cache(self, event):
		entry = self._selected()
		if entry is None or ModelAction.DELETE_CACHE not in (entry.model.actions or ()):
			return
		message = _("Delete these verified add-on-owned files? Configurations remain, but will need their files again. The owned server may stop.\n\n{files}").format(files="\n".join(entry.model.cached_files))
		if wx.MessageBox(message, _("Delete add-on cached files"), wx.YES_NO | wx.ICON_WARNING, parent=self) == wx.YES:
			self._submit(lambda cancel: self._provider.delete_cached_files(entry.model.id), mutation=True,
				feedback=_("Add-on-owned cached files deleted. Configurations were kept."))

	def _visibility_changed(self, event):
		entry = self._selected()
		if entry:
			visible = self._visible.GetValue()
			self._submit(lambda cancel: self._visibility.set_model_visible(self._provider.provider_id, entry.model.id, visible),
				feedback=_("Model selector visibility updated."))

	def _cancel(self, event):
		if self._task:
			if self._task.done:
				self._status.SetLabel(_("Finishing completed operation..."))
				return
			self._task.cancel()
			self._status.SetLabel(_("Stopping operation..."))

	def _close(self, event):
		self._closed = True
		if getattr(self, "_unsubscribe", None):
			self._unsubscribe()
		self._generation += 1
		if self._task:
			self._task.cancel()
		self.EndModal(wx.ID_CANCEL)

	def _operation(self, entry):
		if not entry:
			return None
		return next((op for op in self._provider.model_operations.snapshots() if op.model_id == entry.model.id and op.state in ("queued", "running")), None)

	def _operation_changed(self, snapshot):
		def deliver():
			if self._closed:
				return
			self._status.SetLabel(snapshot.message or snapshot.state)
			if snapshot.state in ("succeeded", "failed", "stopped") or time.monotonic() - self._last_stage_announcement >= 1:
				self._last_stage_announcement = time.monotonic()
				self._speak(snapshot.message or snapshot.state)
			self._update_buttons()
			if snapshot.state in ("succeeded", "failed", "stopped") and self._task is None:
				self.refresh()
		wx.CallAfter(deliver)

	def _lifecycle(self, event):
		entry = self._selected()
		if not entry or not entry.model.registered:
			return
		operation = self._operation(entry)
		if operation:
			self._provider.model_operations.cancel(operation.operation_id)
		else:
			self._provider.model_operations.start(entry.model.id, "unload" if entry.runtime == "loaded" else "load")
		self._update_buttons()

	def _settings(self, event):
		menu = wx.Menu()
		for label, handler in ((_('Runtime settings...'), self._runtime), (_('Generation settings...'), self._generation_settings)):
			item = menu.Append(wx.ID_ANY, label)
			menu.Bind(wx.EVT_MENU, handler, id=item.GetId())
		try:
			self.PopupMenu(menu)
		finally:
			menu.Destroy()

	def _more(self, event):
		menu = wx.Menu()
		entry = self._selected()
		for label, handler, enabled in (
			(_('Duplicate configuration...'), self._duplicate, bool(entry and entry.model.registered)),
			(_('Edit source and companions...'), self._edit_source, bool(entry and entry.model.registered)),
			(_('Locate files...'), self._locate, bool(entry and entry.model.registered)),
			(_('Remove configuration...'), self._remove, bool(entry and entry.model.registered)),
			(_('Delete add-on cached files...'), self._delete_cache, bool(entry and ModelAction.DELETE_CACHE in (entry.model.actions or ()))),
			(_('Import preset once...'), self._import_preset, True)):
			item = menu.Append(wx.ID_ANY, label)
			item.Enable(enabled and not self._operation(entry))
			menu.Bind(wx.EVT_MENU, handler, id=item.GetId())
		try:
			self.PopupMenu(menu)
		finally:
			menu.Destroy()

	def _edit_source(self, event):
		entry = self._selected()
		if not entry:
			return
		from .llama_configuration_dialog import LlamaConfigurationDialog
		dialog = LlamaConfigurationDialog(self, provider=self._provider, initial=self._edit_drafts.get(entry.model.id) or {"source": entry.source_reference, "id": entry.model.id, "name": entry.model.display_name, "companions": getattr(entry, "companions", [])}, editing=True)
		try:
			if dialog.ShowModal() != wx.ID_OK:
				return
			values = dialog.values
			self._edit_drafts[entry.model.id] = values
		finally:
			dialog.Destroy()
		self._submit(lambda cancel: self._provider.update_configuration(entry.model.id, display_name=values["name"], source=values["source"], companions=values["companions"]), mutation=True,
			feedback=_("Configuration updated. Changes apply on the next load."), success=lambda result: self._edit_drafts.pop(entry.model.id, None))

	def _tasks(self, event):
		from .llama_operations_dialog import LlamaOperationsDialog
		dialog = LlamaOperationsDialog(self, self._provider.model_operations)
		try:
			dialog.ShowModal()
		finally:
			dialog.Destroy()
