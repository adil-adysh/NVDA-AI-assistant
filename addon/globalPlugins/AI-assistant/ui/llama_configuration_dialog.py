"""Source/name input for a llama configuration; the manager validates and commits."""
import re
from pathlib import Path
import wx
from gui import guiHelper

from ..core.translation import _
from ..core.cancellation import cancellation_event_scope
from ..core.llama_companions import eligible_artifact
from .task_runner import background_tasks


def configuration_id(name):
	return re.sub(r"[\W_]+", "-", name.strip(), flags=re.UNICODE).strip("-") or "model"


class LlamaConfigurationDialog(wx.Dialog):
	def __init__(self, parent, *, asset=None, initial=None, provider=None, editing=False):
		super().__init__(parent, title=_("Create model configuration"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		initial = initial or {}
		self._provider = provider
		self._asset = asset
		self._editing = editing
		self._task = None
		self._closed = False
		self._files = []
		self._generation = 0
		self._companions = initial.get("companions", [])
		self.Bind(wx.EVT_CLOSE, self._close)

		helper = guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)
		helper.addItem(wx.StaticText(self, label=_("A configuration stores settings and references model files. It does not copy or download weights. Hugging Face references may download on first use.")))
		self._kind = helper.addLabeledControl(_("Model source:"), wx.Choice, choices=[_("Local GGUF"), _("Hugging Face"), _("Existing downloads")])
		self._kind.SetSelection(2 if asset else (1 if initial.get("source", "") and not Path(initial["source"]).is_absolute() else 0))
		self._kind.Bind(wx.EVT_CHOICE, self._source_kind_changed)
		self._folder = wx.Button(self, label=_("Choose downloads folder..."))
		self._folder.Bind(wx.EVT_BUTTON, self._choose_folder)
		helper.addItem(self._folder)
		self._resolve = wx.Button(self, label=_("Resolve repository / browse downloads..."))
		self._resolve.Bind(wx.EVT_BUTTON, self._resolve_source)
		helper.addItem(self._resolve)
		self._artifacts = helper.addLabeledControl(_("Available files (artifact, size and provenance):"), wx.Choice, choices=[])
		self._artifacts.Bind(wx.EVT_CHOICE, self._artifact_changed)
		self._source = helper.addLabeledControl(_("Model file or Hugging Face reference:"), wx.TextCtrl)
		self._source.SetValue(asset.path if asset else initial.get("source", ""))
		self._source.Enable(asset is None)
		browse = wx.Button(self, label=_("Choose GGUF file..."))
		browse.Enable(asset is None)
		browse.Bind(wx.EVT_BUTTON, self._browse)
		helper.addItem(browse)
		self._name = helper.addLabeledControl(_("Configuration name:"), wx.TextCtrl)
		self._name.SetValue(initial.get("name", Path(asset.path).stem if asset else ""))
		self._advanced = wx.CheckBox(self, label=_("Edit advanced configuration ID"))
		helper.addItem(self._advanced)
		self._id = helper.addLabeledControl(_("Configuration ID (used for model requests):"), wx.TextCtrl)
		self._id.SetValue(initial.get("id", configuration_id(self._name.GetValue())))
		self._id.Enable(False)
		self._advanced.Bind(wx.EVT_CHECKBOX, lambda event: self._id.Enable(self._advanced.GetValue()))
		self._name.Bind(wx.EVT_TEXT, self._name_changed)
		self._edit = wx.CheckBox(self, label=_("Edit runtime settings after creating it"))
		helper.addItem(self._edit)
		self._companions_pane = wx.CollapsiblePane(self, label=_("Optional companions"))
		helper.addItem(self._companions_pane, flag=wx.EXPAND)
		self._companions_panel = self._companions_pane.GetPane()
		companion_helper = guiHelper.BoxSizerHelper(self._companions_panel, orientation=wx.VERTICAL)
		self._companion_controls = []
		for role, label in (("vision", _("Vision projector")), ("draft", _("Speculative draft")), ("mtp", _("MTP model (requires explicit supported speculative mode)"))):
			control = companion_helper.addLabeledControl(_("{role} — optional local path or repository#artifact:").format(role=label), wx.TextCtrl)
			current = next((item for item in self._companions if item.get("role") == role), {})
			control.SetValue(current.get("local_path") or (current.get("source", "") + ("#" + current["artifact"] if current.get("artifact") else "")))
			self._companion_controls.append((role, control, current))
			button = wx.Button(self._companions_panel, label=_("Choose {role} source...").format(role=label))
			button.Bind(wx.EVT_BUTTON, lambda event, control=control, role=role: self._pick_companion(control, role))
			companion_helper.addItem(button)
		companion_helper.addItem(wx.StaticText(self._companions_panel, label=_("Companion compatibility is unverified until Load succeeds. Remote files download only during Load or first inference. Multipart primary weights are unsupported.")))
		self._companions_panel.SetSizer(companion_helper.sizer)
		self._companions_pane.Collapse(True)
		helper.addItem(self.CreateButtonSizer(wx.OK | wx.CANCEL))
		self.SetSizerAndFit(helper.sizer)
		self.SetMinSize((560, -1))
		self.SetEscapeId(wx.ID_CANCEL)
		self.SetAffirmativeId(wx.ID_OK)
		self.FindWindowById(wx.ID_OK, self).SetLabel(_("Save") if editing else _("Create"))
		if not editing:
			create_use = wx.Button(self, label=_("Create and use"))
			create_use.Bind(wx.EVT_BUTTON, lambda event: self._accept(event, select=True))
			helper.addItem(create_use)
			helper.addItem(wx.StaticText(self, label=_("Create and use selects the configuration without loading a model.")))
		self.SetSizerAndFit(helper.sizer)
		self._id.Enable(False)
		self._advanced.Enable(not editing)
		self.Bind(wx.EVT_BUTTON, self._close, id=wx.ID_CANCEL)
		self.Bind(wx.EVT_BUTTON, self._accept, id=wx.ID_OK)
		(self._name if asset else self._source).SetFocus()

	def _name_changed(self, event):
		if not self._editing and not self._advanced.GetValue():
			self._id.SetValue(configuration_id(self._name.GetValue()))
		event.Skip()

	def _browse(self, event):
		dialog = wx.FileDialog(self, message=_("Choose model file"), wildcard=_("GGUF files (*.gguf)|*.gguf"), style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
		try:
			if dialog.ShowModal() == wx.ID_OK:
				self._asset = None
				self._source.SetValue(dialog.GetPath())
				if not self._name.GetValue().strip():
					self._name.SetValue(Path(dialog.GetPath()).stem)
		finally:
			dialog.Destroy()

	def _accept(self, event, *, select=False):
		for control in (self._source, self._name, self._id):
			if not control.GetValue().strip():
				wx.MessageBox(_("Enter a source, name and configuration ID."), _("Incomplete configuration"), wx.OK | wx.ICON_ERROR, parent=self)
				control.SetFocus()
				return
		companions = []
		for role, control, current in self._companion_controls:
			reference = control.GetValue().strip()
			if not reference:
				continue
			if current and reference == (current.get("local_path") or current.get("source", "") + ("#" + current["artifact"] if current.get("artifact") else "")):
				companions.append(current)
				continue
			if Path(reference).is_absolute():
				companions.append({"role": role, "source": reference, "kind": "local_file", "local_path": reference, "ownership": "user"})
			elif "#" in reference:
				repo, artifact = reference.split("#", 1)
				companions.append({"role": role, "source": repo, "kind": "hugging_face", "artifact": artifact.removeprefix("file="), "ownership": "user"})
			else:
				wx.MessageBox(_("A remote companion needs an explicit repository#artifact reference."), _("Incomplete companion"), wx.OK | wx.ICON_ERROR, parent=self)
				control.SetFocus()
				return
		self.values = {"companions": companions, "asset_token": self._asset.token if self._asset else None,"source": self._source.GetValue().strip(), "name": self._name.GetValue().strip(),
			"id": self._id.GetValue().strip(), "select": select, "edit": self._edit.GetValue()}
		self._closed = True
		self._generation += 1
		if self._task:
			self._task.cancel()
		self.EndModal(wx.ID_OK)

	def _source_kind_changed(self, event):
		self._generation += 1
		if self._task:
			self._task.cancel()
			self._task = None
		self._resolve.Enable(True)
		self._asset = None
		self._source.Enable(self._kind.GetSelection() != 2)
		self._files = []
		self._artifacts.Clear()

	def _resolve_source(self, event):
		if self._task or not self._provider:
			return
		kind = self._kind.GetSelection()
		self._generation += 1
		generation = self._generation
		if kind == 0:
			self._browse(event)
			return
		reference = self._source.GetValue().strip().split("#", 1)[0]
		def work(cancel):
			with cancellation_event_scope(cancel):
				if kind == 1:
					result = self._provider.resolve_hf(reference, role="primary")
					return result.get("files", []) if isinstance(result, dict) else result.files
				self._provider.discover_assets(getattr(self, "_roots", None))
				return [entry.asset for entry in self._provider.list_model_entries() if entry.kind == "downloaded"]
		def ready(files):
			if self._closed or generation != self._generation:
				return
			self._files = files
			self._artifacts.Clear()
			for item in files:
				size = item.get("size_bytes") if isinstance(item, dict) else item.size_bytes
				name = item.get("artifact", "") if isinstance(item, dict) else item.path
				provenance = reference if isinstance(item, dict) else item.source
				if not isinstance(item, dict) and not eligible_artifact(item.path):
					name = _("{file} (unavailable as primary: projector or multipart shard)").format(file=name)
				self._artifacts.Append(_("{file}; {size}; {source}").format(file=name, size=_("{size} bytes").format(size=size) if size is not None else _("Unknown size"), source=provenance))
		def failed(error):
			if self._closed or generation != self._generation:
				return
			from ..service.error_reporter import ErrorContext, error_reporter
			error_reporter.report(error, ErrorContext(operation="llama source resolution", provider=self._provider.provider_id, origin="model manager"), owner=lambda presentation: wx.MessageBox(presentation.message, presentation.title, wx.OK | wx.ICON_ERROR, parent=self))
		def finished():
			if self._closed or generation != self._generation:
				return
			self._task = None
			self._resolve.Enable(True)
		self._resolve.Enable(False)
		self._task = background_tasks.submit(work, on_success=ready, on_error=failed, on_finally=finished, is_alive=lambda: not self._closed)

	def _artifact_changed(self, event):
		index = self._artifacts.GetSelection()
		if not 0 <= index < len(self._files):
			return
		item = self._files[index]
		if isinstance(item, dict):
			if not item.get("eligible", True):
				wx.MessageBox(_("This artifact cannot be used as a primary model. Multipart primary weights are unsupported."), _("Unsupported artifact"), wx.OK | wx.ICON_ERROR, parent=self)
				return
			repo = self._source.GetValue().split("#", 1)[0]
			self._source.SetValue(repo + "#file=" + item["artifact"])
			name = Path(item["artifact"]).stem
		else:
			if not eligible_artifact(item.path):
				wx.MessageBox(_("This file is a projector or multipart shard and cannot be used as a primary model. Choose a standalone GGUF; projector files belong in Optional companions."), _("Unsupported primary file"), wx.OK | wx.ICON_ERROR, parent=self)
				return
			self._asset = item
			self._source.SetValue(item.path)
			name = Path(item.path).stem
		if not self._name.GetValue().strip():
			self._name.SetValue(name)

	def _close(self, event):
		self._closed = True
		self._generation += 1
		if self._task:
			self._task.cancel()
		self.EndModal(wx.ID_CANCEL)

	def _choose_folder(self, event):
		dialog = wx.DirDialog(self, _("Choose a downloads folder"))
		try:
			if dialog.ShowModal() != wx.ID_OK:
				return
			self._roots = [{"path": dialog.GetPath(), "source": "user_folder"}]
		finally:
			dialog.Destroy()
		self._kind.SetSelection(2)
		self._source_kind_changed(None)
		self._resolve_source(None)

	def _pick_companion(self, control, role):
		choice = wx.SingleChoiceDialog(self, _("Choose the companion file source."), _("Companion source"), [_("Local GGUF"), _("Existing downloads"), _("Hugging Face")])
		try:
			if choice.ShowModal() != wx.ID_OK:
				return
			kind = choice.GetSelection()
		finally:
			choice.Destroy()
		if kind == 0:
			dialog = wx.FileDialog(self, message=_("Choose companion GGUF"), wildcard=_("GGUF files (*.gguf)|*.gguf"), style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
			try:
				if dialog.ShowModal() == wx.ID_OK:
					control.SetValue(dialog.GetPath())
			finally:
				dialog.Destroy()
			return
		if not self._provider or self._task:
			return
		repository = ""
		if kind == 2:
			dialog = wx.TextEntryDialog(self, _("Hugging Face repository (owner/name):"), _("Resolve companion files"))
			try:
				if dialog.ShowModal() != wx.ID_OK:
					return
				repository = dialog.GetValue().strip()
			finally:
				dialog.Destroy()
		self._generation += 1
		generation = self._generation
		def work(cancel):
			with cancellation_event_scope(cancel):
				if kind == 2:
					result = self._provider.resolve_hf(repository, role=role)
					return [item for item in result.get("files", []) if item.get("eligible", True)]
				self._provider.discover_assets(getattr(self, "_roots", None))
				return [entry.asset for entry in self._provider.list_model_entries() if entry.kind == "downloaded"]
		def ready(assets):
			if self._closed or generation != self._generation:
				return
			if kind == 2:
				dialog = wx.SingleChoiceDialog(self, _("Choose a companion artifact. Downloads happen during Load."), _("Hugging Face companions"), [_("{artifact}; {size}").format(artifact=item["artifact"], size=_("{size} bytes").format(size=item["size_bytes"]) if item.get("size_bytes") is not None else _("Unknown size")) for item in assets])
				try:
					if dialog.ShowModal() == wx.ID_OK and assets:
						item = assets[dialog.GetSelection()]
						control.SetValue(repository + "#file=" + item["artifact"])
				finally:
					dialog.Destroy()
				return
			dialog = wx.SingleChoiceDialog(self, _("Choose a cached companion; files will be linked."), _("Existing downloads"), [_("{path}; {size}; {source}").format(path=asset.path, size=_("{size} bytes").format(size=asset.size_bytes) if asset.size_bytes is not None else _("Unknown size"), source=asset.source) for asset in assets])
			try:
				if dialog.ShowModal() == wx.ID_OK and assets:
					asset = assets[dialog.GetSelection()]
					control.SetValue(asset.path)
					for index, (item_role, item_control, current) in enumerate(self._companion_controls):
						if item_control is control:
							self._companion_controls[index] = (item_role, control, {"role": role, "source": asset.path, "kind": "local_file", "local_path": asset.path, "artifact": asset.artifact, "revision": asset.revision, "ownership": "user", "asset_token": asset.token})
			finally:
				dialog.Destroy()
		def finished():
			if generation == self._generation:
				self._task = None
		self._task = background_tasks.submit(work, on_success=ready, on_finally=finished, is_alive=lambda: not self._closed)
