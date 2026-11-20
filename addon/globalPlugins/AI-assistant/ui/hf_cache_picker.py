"""Reusable read-only picker for GGUF files in the Hugging Face cache."""
from __future__ import annotations

import wx
from gui import guiHelper

from ..core.hf_cache import CachedArtifact, CachedRepository, scan_cached_artifacts
from ..core.translation import _
from .task_runner import background_tasks

ROLE_LABELS = {
	"main": _("Model"),
	"draft": _("Draft"),
	"projector": _("Projector"),
}
KIND_TITLES = {
	"main": _("Choose cached main model"),
	"draft": _("Choose cached draft model"),
	"projector": _("Cached projectors"),
}
KIND_FILTERS = {
	"main": {"main"},
	"draft": {"draft"},
	"projector": {"projector"},
}


def format_size(value: int) -> str:
	if value <= 0:
		return _("unknown size")
	units = ("B", "KB", "MB", "GB", "TB")
	size = float(value)
	for unit in units:
		if size < 1024 or unit == units[-1]:
			return _("{size:.1f} {unit}").format(size=size, unit=unit)
		size /= 1024
	return _("unknown size")


def _labeled(helper, parent, label, control_class, **kwargs):
	labeled = guiHelper.LabeledControlHelper(parent, label, control_class, **kwargs)
	helper.addItem(labeled.sizer, flag=wx.EXPAND)
	return labeled.control


def _labeled_multiline(helper, parent, label, control_class=wx.TextCtrl, *, proportion=0, **kwargs):
	label_control = wx.StaticText(parent, label=label)
	control = control_class(parent, **kwargs)
	sizer = wx.BoxSizer(wx.VERTICAL)
	sizer.Add(label_control)
	sizer.AddSpacer(4)
	sizer.Add(control, 1 if proportion else 0, wx.EXPAND)
	helper.addItem(sizer, flag=wx.EXPAND, proportion=proportion)
	return control


class CachedSourcePicker(wx.Dialog):
	"""Select one exact cached GGUF, or inspect cached projectors read-only."""

	def __init__(self, parent, *, kind: str, initial_repo: str = "",
			initial_file: str = "") -> None:
		if kind not in KIND_TITLES:
			raise ValueError(f"unknown cache picker kind: {kind}")
		super().__init__(parent, title=KIND_TITLES[kind],
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self._kind = kind
		self._initial_repo = initial_repo
		self._initial_file = initial_file
		self._repositories: tuple[CachedRepository, ...] = ()
		self._repo_rows: list[CachedRepository] = []
		self._file_rows: list[CachedArtifact] = []
		self._task = None
		self._closed = False
		self.result: tuple[str, str] | None = None
		self._build_ui()
		self._scan()

	def _build_ui(self) -> None:
		helper = guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)
		intro = _(
			"Read-only view of the local cache. Selecting a file stores only its "
			"repository and exact filename, not a local path or commit."
		) if self._kind != "projector" else _(
			"Read-only list of cached projectors. llama.cpp chooses a projector "
			"automatically from the model repository; this list does not select one."
		)
		helper.addItem(wx.StaticText(self, label=intro))
		self._cache_path = wx.StaticText(self, label="")
		self._cache_path.SetName(_("Cache roots"))
		helper.addItem(self._cache_path)
		self._status = wx.StaticText(self, label=_("Scanning Hugging Face cache..."))
		self._status.SetName(_("Cache status"))
		helper.addItem(self._status)

		repo_label = guiHelper.LabeledControlHelper(
			self, _("&Repositories:"), wx.ListCtrl,
			style=wx.LC_REPORT | wx.LC_SINGLE_SEL, size=(-1, 160))
		self._repos = repo_label.control
		for title, width in ((_("Repository"), 410), (_("Files"), 55), (_("Revision"), 120)):
			self._repos.AppendColumn(title, width=width)
		self._repos.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda event: self._populate_files())
		self._repos.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda event: self._populate_files())
		helper.addItem(repo_label.sizer, flag=wx.EXPAND, proportion=1)

		self._filter = _labeled(helper, self,
			_("&Filter files:"), wx.TextCtrl, style=wx.TE_PROCESS_ENTER)
		self._filter.SetHint(_("Filter by filename or quant"))
		self._filter.Bind(wx.EVT_TEXT, lambda event: self._populate_files())
		self._show_all = wx.CheckBox(self, label=_("Show all files"))
		self._show_all.Bind(wx.EVT_CHECKBOX, lambda event: self._populate_files())
		helper.addItem(self._show_all)

		file_label = guiHelper.LabeledControlHelper(
			self, _("Files in selected &repository:"), wx.ListCtrl,
			style=wx.LC_REPORT | wx.LC_SINGLE_SEL, size=(-1, 230))
		self._files = file_label.control
		for title, width in ((_("Quant"), 110), (_("File"), 400), (_("Role"), 90),
				(_("Size"), 90), (_("State"), 100)):
			self._files.AppendColumn(title, width=width)
		self._files.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda event: self._selection_changed())
		self._files.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda event: self._accept())
		helper.addItem(file_label.sizer, flag=wx.EXPAND, proportion=2)

		self._details = _labeled_multiline(helper, self, _("&Details:"),
			style=wx.TE_READONLY | wx.TE_MULTILINE, size=(-1, 105))
		helper.addItem(wx.StaticText(self, label=_(
			"Cached means the file is readable now. It does not mean the model will load.")))

		buttons = wx.BoxSizer(wx.HORIZONTAL)
		self._rescan = wx.Button(self, label=_("Rescan"))
		self._rescan.Bind(wx.EVT_BUTTON, lambda event: self._scan())
		buttons.Add(self._rescan, 0, wx.RIGHT, 6)
		buttons.AddStretchSpacer()
		if self._kind == "projector":
			close = wx.Button(self, id=wx.ID_CANCEL, label=_("Close"))
			buttons.Add(close)
		else:
			self._ok = wx.Button(self, id=wx.ID_OK, label=_("OK"))
			self._ok.Enable(False)
			self._ok.Bind(wx.EVT_BUTTON, lambda event: self._accept())
			buttons.Add(self._ok, 0, wx.RIGHT, 6)
			buttons.Add(wx.Button(self, id=wx.ID_CANCEL, label=_("Cancel")))
		helper.addItem(buttons, flag=wx.EXPAND)
		self._filter.SetMinSize((680, -1))
		self._details.SetMinSize((760, 105))
		self.SetSizer(helper.sizer)
		self.SetSize((900, 820))
		self.SetMinSize((760, 620))
		self._centre_on_screen()
		wx.CallAfter(self._centre_on_screen)
		self.SetEscapeId(wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, self._close)
		self.Bind(wx.EVT_CHAR_HOOK, self._key)
		self._repos.SetFocus()

	def _centre_on_screen(self) -> None:
		self.Layout()
		area = wx.Display().GetClientArea()
		size = self.GetSize()
		self.SetPosition((
			area.x + max(0, (area.width - size.width) // 2),
			area.y + max(0, (area.height - size.height) // 2),
		))

	def _key(self, event) -> None:
		if event.GetKeyCode() == wx.WXK_F5:
			self._scan()
			return
		event.Skip()

	def _close(self, event) -> None:
		self._closed = True
		if self._task is not None:
			self._task.cancel()
			self._task = None
		self.Destroy()

	def _scan(self) -> None:
		if self._task is not None:
			return
		self._files.Enable(False)
		self._rescan.Enable(False)
		self._status.SetLabel(_("Scanning Hugging Face cache..."))
		self._cache_path.SetLabel("")
		def work(cancel):
			return scan_cached_artifacts(cancelled=cancel.is_set)
		def done(repositories):
			if self._closed:
				return
			self._repositories = tuple(repositories)
			self._cache_path.SetLabel(_("Cache roots: {roots}").format(
				roots="; ".join(str(path) for path in _cache_roots_display())))
			self._populate_repositories()
			self._repos.Enable(True)
			self._files.Enable(True)
			self._rescan.Enable(True)
			count = sum(len(repo.artifacts) for repo in self._repositories)
			self._status.SetLabel(_("{repos} repositories, {files} readable GGUF files.").format(
				repos=len(self._repositories), files=count) if self._repositories else
				_("No readable GGUF files were found in the Hugging Face cache."))
		def failed(error):
			if self._closed:
				return
			self._repos.Enable(True)
			self._files.Enable(True)
			self._rescan.Enable(True)
			self._status.SetLabel(str(error))
		def finished():
			self._task = None
		self._task = background_tasks.submit(work, on_success=done, on_error=failed,
			on_finally=finished, is_alive=lambda: not self._closed,
			task_name="scan hugging face cache")

	def _populate_repositories(self) -> None:
		self._repos.DeleteAllItems()
		self._repo_rows = list(self._repositories)
		selected = next((index for index, repo in enumerate(self._repo_rows)
			if repo.repo == self._initial_repo), None)
		if selected is None:
			allowed = KIND_FILTERS[self._kind]
			selected = next((index for index, repo in enumerate(self._repo_rows)
				if any(item.role in allowed for item in repo.artifacts)), 0)
		for repo in self._repo_rows:
			index = self._repos.InsertItem(self._repos.GetItemCount(), repo.repo)
			self._repos.SetItem(index, 1, str(len(repo.artifacts)))
			revision = repo.revision[:8] + ("" if repo.revision_confirmed else _(" (unconfirmed)"))
			self._repos.SetItem(index, 2, revision)
		if self._repo_rows:
			self._repos.Select(selected)
			self._repos.Focus(selected)
		self._populate_files()

	def _selected_repository(self) -> CachedRepository | None:
		index = self._repos.GetFirstSelected()
		return self._repo_rows[index] if 0 <= index < len(self._repo_rows) else None

	def _populate_files(self) -> None:
		repo = self._selected_repository()
		self._files.DeleteAllItems()
		self._file_rows = []
		self._details.SetValue("")
		if repo is None:
			self._set_ok(False)
			return
		allowed = KIND_FILTERS[self._kind]
		text = self._filter.GetValue().strip().casefold()
		for artifact in repo.artifacts:
			if not self._show_all.GetValue() and artifact.role not in allowed:
				continue
			if text and text not in artifact.path.casefold() and text not in artifact.quant.casefold():
				continue
			self._file_rows.append(artifact)
		for artifact in self._file_rows:
			index = self._files.InsertItem(self._files.GetItemCount(), artifact.quant or "-")
			self._files.SetItem(index, 1, artifact.path)
			self._files.SetItem(index, 2, ROLE_LABELS.get(artifact.role, _("Unclassified")))
			self._files.SetItem(index, 3, format_size(artifact.size))
			state = _("Incomplete split") if not artifact.complete else _("Cached")
			self._files.SetItem(index, 4, state)
		initial = next((index for index, artifact in enumerate(self._file_rows)
			if artifact.path == self._initial_file), None)
		if initial is not None:
			self._files.Select(initial)
			self._files.Focus(initial)
		self._selection_changed()
		hidden = len(repo.artifacts) - len(self._file_rows)
		if self._file_rows:
			suffix = _(" {count} hidden by the current filter.").format(count=hidden) if hidden else ""
			self._status.SetLabel(_("{count} file(s) shown.{suffix}").format(
				count=len(self._file_rows), suffix=suffix))
		else:
			self._status.SetLabel(_("No matching files in this repository. Try Show all files."))

	def _selected_artifact(self) -> CachedArtifact | None:
		index = self._files.GetFirstSelected()
		return self._file_rows[index] if 0 <= index < len(self._file_rows) else None

	def _selection_changed(self) -> None:
		artifact = self._selected_artifact()
		repository = self._selected_repository()
		self._set_ok(
			artifact is not None
			and artifact.complete
			and repository is not None
			and repository.revision_confirmed
		)
		if artifact is None:
			self._details.SetValue("")
			return
		split = _("none") if artifact.parts <= 1 else (
			_("complete ({parts} parts)").format(parts=artifact.parts) if artifact.complete
			else _("incomplete ({parts} parts expected)").format(parts=artifact.parts))
		lines = [
			_("Repository: {repo}").format(repo=artifact.repo),
			_("Revision: {revision} (observed; the preset follows main, not pinned)").format(
				revision=artifact.revision[:12]),
			_("File: {file}").format(file=artifact.path),
			_("Architecture: {architecture}").format(architecture=artifact.architecture or _("unknown")),
			_("Size: {size}").format(size=format_size(artifact.size)),
			_("Split: {split}").format(split=split),
			_("State: {state}").format(state=(
				_("Incomplete split, not selectable") if not artifact.complete
				else _("Cached, runtime unverified"))),
		]
		self._details.SetValue("\n".join(lines))

	def _set_ok(self, enabled: bool) -> None:
		button = getattr(self, "_ok", None)
		if button is not None:
			button.Enable(bool(enabled))

	def _accept(self) -> None:
		if self._kind == "projector":
			return
		repository = self._selected_repository()
		artifact = self._selected_artifact()
		if artifact is None or not artifact.complete or repository is None or not repository.revision_confirmed:
			return
		self.result = (artifact.repo, artifact.path)
		self.EndModal(wx.ID_OK)


def _cache_roots_display():
	from ..core.hf_cache import cache_roots
	return cache_roots()


__all__ = ["CachedSourcePicker", "format_size"]
