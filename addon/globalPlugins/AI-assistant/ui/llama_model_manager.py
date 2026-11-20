"""Advanced llama.cpp preset manager. Hugging Face presets only."""
import wx
from gui import guiHelper

from ..core.translation import _
from ..service.error_reporter import ErrorContext, error_reporter
from .llama_preset_dialog import LlamaPresetDialog
from .task_runner import background_tasks


class LlamaModelsDialog(wx.Dialog):
	def __init__(self, parent, provider):
		super().__init__(parent, title=_("llama.cpp presets (advanced)"),
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self._provider = provider
		self._records = ()
		self._task = None
		self._closed = False
		helper = guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)
		helper.addItem(wx.StaticText(self, label=_(
			"Manage saved model presets. OK in the editor saves a preset; Close leaves saved changes in place.")))
		self._list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
		self._list.SetName(_("Model presets"))
		for name, width in ((_("Name"), 200), (_("Source"), 340), (_("Mode"), 80),
				(_("Draft"), 100), (_("Selected"), 75), (_("Runtime"), 120)):
			self._list.AppendColumn(name, width=width)
		self._list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda event: self._selection_changed())
		self._list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda event: self._edit())
		helper.addItem(self._list, flag=wx.EXPAND, proportion=1)
		self._details = helper.addLabeledControl(_("Selected preset:"), wx.TextCtrl,
			style=wx.TE_READONLY | wx.TE_MULTILINE, size=(-1, 100))
		self._status = wx.StaticText(self, label=_("Loading presets..."))
		helper.addItem(self._status)
		buttons = wx.WrapSizer(wx.HORIZONTAL)
		self._buttons = {}
		for key, label, handler in (
			("add", _("Add preset..."), self._add),
			("edit", _("Edit..."), self._edit),
			("duplicate", _("Duplicate..."), self._duplicate),
			("remove", _("Remove"), self._remove),
			("refresh", _("Refresh"), self._refresh),
		):
			button = wx.Button(self, label=label)
			button.Bind(wx.EVT_BUTTON, handler)
			buttons.Add(button, 0, wx.ALL, 3)
			self._buttons[key] = button
		helper.addItem(buttons)
		close = wx.Button(self, id=wx.ID_CANCEL, label=_("&Close"))
		close.Bind(wx.EVT_BUTTON, self._close)
		helper.addItem(close, flag=wx.ALIGN_RIGHT)
		self.SetSizer(helper.sizer)
		self.SetSize((820, 620))
		self._centre_on_screen()
		wx.CallAfter(self._centre_on_screen)
		self.SetEscapeId(wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, self._close)
		self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
		self._selection_changed()
		self._refresh()

	def _centre_on_screen(self) -> None:
		self.Layout()
		area = wx.Display().GetClientArea()
		size = self.GetSize()
		self.SetPosition((
			area.x + max(0, (area.width - size.width) // 2),
			area.y + max(0, (area.height - size.height) // 2),
		))

	def _close(self, event):
		self._dispose()
		if self.IsModal():
			self.EndModal(wx.ID_CANCEL)
		else:
			self.Destroy()

	def _on_destroy(self, event):
		if not self or event.GetEventObject() is self:
			self._dispose()
		event.Skip()

	def _dispose(self):
		self._closed = True
		if self._task is not None:
			self._task.cancel()
			self._task = None

	def _selected(self):
		index = self._list.GetFirstSelected()
		return self._records[index] if 0 <= index < len(self._records) else None

	def _refresh(self, event=None):
		if self._task is not None:
			return
		self._status.SetLabel(_("Refreshing presets..."))
		def work(cancel):
			records = self._provider.list_presets()
			models = self._provider.list_server_models(refresh=True)
			return records, {str(item.get("id", "")): item.get("status") or {} for item in models}
		def show(result):
			selected = self._selected()
			selected_id = selected.model_id if selected else None
			self._records, statuses = result
			self._list.DeleteAllItems()
			active = self._provider.active_model_id
			for record in self._records:
				index = self._list.InsertItem(self._list.GetItemCount(), record.display_name or record.model_id)
				source = record.repo + (f" - {record.file}" if record.file else "")
				self._list.SetItem(index, 1, source)
				self._list.SetItem(index, 2, _("Cached") if record.file else _("Manual"))
				if record.draft_repo:
					self._list.SetItem(index, 3, _("Cached") if record.draft_file else _("Manual"))
				self._list.SetItem(index, 4, _("Yes") if record.model_id == active else "")
				status = statuses.get(record.model_id) or {}
				value = status.get("value", "unknown") if isinstance(status, dict) else "unknown"
				if isinstance(status, dict) and status.get("failed"):
					value = _("Failed")
				self._list.SetItem(index, 5, str(value))
				if record.model_id == selected_id:
					self._list.Select(index)
					self._list.Focus(index)
			count = len(self._records)
			self._status.SetLabel(_("{count} preset(s).").format(count=count) if count else
				_("No presets yet. Add a Hugging Face repository to create one."))
			self._selection_changed()
		def failed(error):
			error_reporter.report(error, ErrorContext(operation="list llama.cpp presets", provider=self._provider.provider_id, origin="model manager"),
				owner=lambda presentation: self._status.SetLabel(presentation.message))
		def finished():
			self._task = None
			self._selection_changed()
		self._task = background_tasks.submit(work, on_success=show, on_error=failed, on_finally=finished,
			is_alive=lambda: not self._closed)

	def _selection_changed(self):
		record = self._selected()
		for key in ("edit", "duplicate", "remove"):
			self._buttons[key].Enable(record is not None and self._task is None)
		if record is None:
			self._details.SetValue("")
			return
		lines = [
			_("ID: {id}").format(id=record.model_id),
			_("Repository: {repo}").format(repo=record.repo),
			_("Source: {source}").format(source=_("Cached file") if record.file else _("Manual reference")),
		]
		if record.file:
			lines.append(_("File: {file}").format(file=record.file))
		if record.draft_repo:
			lines.append(_("Draft repository: {repo}").format(repo=record.draft_repo))
		if record.draft_file:
			lines.append(_("Draft file: {file}").format(file=record.draft_file))
		if record.preset_options.get("spec-type"):
			lines.append(_("Speculative mode: {mode}").format(mode=record.preset_options["spec-type"]))
		lines.append(_("Projector: {mode}").format(
			mode=_("Disabled") if record.preset_options.get("mmproj-auto") == "false" else _("Automatic")))
		if record.preset_options:
			lines.append(_("Runtime options: {options}").format(
				options="; ".join(f"{key} = {value}" for key, value in sorted(record.preset_options.items()))))
		self._details.SetValue("\n".join(lines))

	def _add(self, event):
		dialog = LlamaPresetDialog(self, self._provider)
		try:
			if dialog.ShowModal() == wx.ID_OK:
				self._refresh()
		finally:
			dialog.Destroy()

	def _edit(self, event=None):
		record = self._selected()
		if record is None:
			return
		dialog = LlamaPresetDialog(self, self._provider, record)
		try:
			if dialog.ShowModal() == wx.ID_OK:
				self._refresh()
		finally:
			dialog.Destroy()

	def _duplicate(self, event):
		record = self._selected()
		if record is None:
			return
		dialog = wx.TextEntryDialog(self, _("New preset ID:"), _("Duplicate preset"), f"{record.model_id}-copy")
		try:
			if dialog.ShowModal() != wx.ID_OK:
				return
			new_id = dialog.GetValue().strip()
		finally:
			dialog.Destroy()
		try:
			self._provider.duplicate_preset(record.model_id, new_id, _("{name} copy").format(name=record.display_name or record.model_id))
		except Exception as error:
			wx.MessageBox(str(error), _("Duplicate preset"), wx.OK | wx.ICON_ERROR, parent=self)
			return
		self._refresh()

	def _remove(self, event):
		record = self._selected()
		if record is None:
			return
		if wx.MessageBox(_("Remove preset {name}? Model files in the Hugging Face cache are kept.").format(
				name=record.display_name or record.model_id), _("Remove preset"),
				wx.YES_NO | wx.ICON_QUESTION, parent=self) != wx.YES:
			return
		try:
			self._provider.delete_model(record.model_id)
		except Exception as error:
			wx.MessageBox(str(error), _("Remove preset"), wx.OK | wx.ICON_ERROR, parent=self)
			return
		self._refresh()
