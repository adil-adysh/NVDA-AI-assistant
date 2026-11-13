"""Retained application-owned lifecycle operations; dismissal only detaches."""
import wx
from gui import guiHelper
from ..core.translation import _


def operation_label(value):
	return {"load": _("Load"), "unload": _("Unload"), "queued": _("Queued"), "running": _("Running"), "succeeded": _("Succeeded"), "failed": _("Failed"), "stopped": _("Stopped")}.get(value, _("Unknown"))


class LlamaOperationsDialog(wx.Dialog):
	def __init__(self, parent, registry):
		super().__init__(parent, title=_("Model tasks"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self._registry = registry
		self._closed = False
		self._rows = []
		helper = guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)
		self._list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
		for label in (_("Model"), _("Operation"), _("State"), _("Details")):
			self._list.AppendColumn(label, width=180)
		helper.addItem(self._list, proportion=1, flag=wx.EXPAND)
		self._details = helper.addLabeledControl(_("Selected task history and error:"), wx.TextCtrl, style=wx.TE_READONLY | wx.TE_MULTILINE)
		self._list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._selection_changed)
		stop = wx.Button(self, label=_("Stop selected task"))
		stop.Bind(wx.EVT_BUTTON, self._stop)
		helper.addItem(stop)
		close = wx.Button(self, wx.ID_CANCEL, _("Close"))
		close.Bind(wx.EVT_BUTTON, self._close)
		helper.addItem(close)
		self.Bind(wx.EVT_CLOSE, self._close)
		self.SetEscapeId(wx.ID_CANCEL)
		self.SetSizer(helper.sizer)
		self.SetSize((780, 420))
		self._unsubscribe = registry.subscribe(self._changed)
		self._render()
		self._list.SetFocus()

	def _render(self):
		if self._closed:
			return
		selected = self._list.GetFirstSelected()
		identity = self._rows[selected].operation_id if 0 <= selected < len(self._rows) else None
		self._rows = list(self._registry.snapshots())
		self._list.DeleteAllItems()
		for row in self._rows:
			index = self._list.InsertItem(self._list.GetItemCount(), row.model_id)
			for column, value in enumerate((operation_label(row.kind), operation_label(row.state), row.message or ""), 1):
				self._list.SetItem(index, column, value)
			if row.operation_id == identity:
				self._list.Select(index)

		self._selection_changed(None)

	def _selection_changed(self, event):
		index = self._list.GetFirstSelected()
		if 0 <= index < len(self._rows):
			row = self._rows[index]
			self._details.SetValue("\n".join((*row.history, row.error or "")))
		else:
			self._details.SetValue("")

	def _changed(self, snapshot):
		wx.CallAfter(self._render)

	def _stop(self, event):
		index = self._list.GetFirstSelected()
		if 0 <= index < len(self._rows):
			row = self._rows[index]
			if row.state in ("queued", "running"):
				self._registry.cancel(row.operation_id)

	def _close(self, event):
		self._closed = True
		self._unsubscribe()
		self.EndModal(wx.ID_CANCEL)
