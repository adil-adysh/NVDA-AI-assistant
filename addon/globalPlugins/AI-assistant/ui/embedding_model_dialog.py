# -*- coding: utf-8 -*-
"""Accessible native management UI for local embedding models."""
from __future__ import annotations

import builtins
from typing import Callable, cast

import wx

from ..config.settings import get_embedding_model, set_embedding_model
from ..embeddings.manager import EmbeddingModelInfo, embedding_model_service
from ..service.error_reporter import ErrorContext, error_reporter
from .download_progress import DownloadProgressDialog
from .task_runner import TaskHandle, background_tasks

_ = cast(Callable[[str], str], getattr(builtins, "_", lambda text: text))


class EmbeddingModelManagementDialog(wx.Dialog):
	def __init__(self, parent: wx.Window) -> None:
		super().__init__(parent, title=_("Manage Embedding Models"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self._models: tuple[EmbeddingModelInfo, ...] = ()
		self._cached: dict[str, bool] = {}
		self._status_task: TaskHandle[tuple[tuple[EmbeddingModelInfo, ...], dict[str, bool]]] | None = None
		self._delete_task: TaskHandle[None] | None = None
		self._destroyed = False
		self._build_ui()
		self._update_buttons()
		self._refresh_catalog()
		self.Bind(wx.EVT_CLOSE, self._on_close)
		self.CentreOnParent()

	def _refresh_catalog(self) -> None:
		self._status_task = background_tasks.submit(
			lambda cancel: embedding_model_service.catalog(cancel_event=cancel),
			on_success=self._on_catalog_loaded,
			on_error=lambda error: error_reporter.report(
				error, ErrorContext(operation="inspect embedding models", origin="embedding model manager"),
				owner=lambda presentation: wx.MessageBox(
					presentation.message, presentation.title, wx.ICON_ERROR, parent=self,
				),
			),
			on_finally=self._finish_refresh,
			is_alive=lambda: not self._destroyed,
		)
		self._update_buttons()

	def _finish_refresh(self) -> None:
		self._status_task = None
		self._update_buttons()

	def _on_catalog_loaded(self, catalog: tuple[tuple[EmbeddingModelInfo, ...], dict[str, bool]]) -> None:
		selected = self._selected()
		self._models, self._cached = catalog
		self._list.DeleteAllItems()
		for model in self._models:
			index = self._list.InsertItem(self._list.GetItemCount(), model.name)
			self._list.SetItem(index, 2, str(model.dimensions))
			self._list.SetItem(index, 3, f"{model.max_tokens:,}")
			self._list.SetItem(index, 4, _("{size:.0f} MB").format(size=model.size_mb))
		if self._models:
			preferred = selected.id if selected is not None else get_embedding_model()
			index = next((index for index, model in enumerate(self._models) if model.id == preferred), 0)
			self._list.Select(index)
			self._list.Focus(index)
		self._refresh_rows()

	def _build_ui(self) -> None:
		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.Add(wx.StaticText(self, label=_("Download a model and set it active to use embeddings for page chat.")), 0, wx.ALL | wx.EXPAND, 10)
		self._list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_HRULES)
		self._list.SetName(_("Embedding model catalog"))
		for title, width in ((_("Model"), 180), (_("Status"), 100), (_("Dimensions"), 90), (_("Context"), 90), (_("Size"), 90), (_("Active"), 70)):
			self._list.AppendColumn(title, width=width)
		self._list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda _event: self._update_buttons())
		sizer.Add(self._list, 1, wx.ALL | wx.EXPAND, 10)
		buttons = wx.BoxSizer(wx.HORIZONTAL)
		self._prepare = wx.Button(self, label=_("Download / Prepare"))
		self._prepare.Bind(wx.EVT_BUTTON, self._on_prepare)
		buttons.Add(self._prepare, 0, wx.RIGHT, 6)
		self._active = wx.Button(self, label=_("Set Active"))
		self._active.Bind(wx.EVT_BUTTON, self._on_active)
		buttons.Add(self._active, 0, wx.RIGHT, 6)
		self._delete = wx.Button(self, label=_("Delete Cache"))
		self._delete.Bind(wx.EVT_BUTTON, self._on_delete)
		buttons.Add(self._delete, 0, wx.RIGHT, 6)
		close = wx.Button(self, wx.ID_CLOSE, label=_("Close"))
		close.Bind(wx.EVT_BUTTON, self._on_close)
		self.SetEscapeId(wx.ID_CLOSE)
		buttons.Add(close)
		sizer.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 10)
		self.SetSizerAndFit(sizer)
		self.SetMinSize((620, 380))

	def _selected(self) -> EmbeddingModelInfo | None:
		index = self._list.GetFirstSelected()
		return self._models[index] if 0 <= index < len(self._models) else None

	def _refresh_rows(self) -> None:
		active = get_embedding_model()
		for index, model in enumerate(self._models):
			self._list.SetItem(index, 1, _("Downloaded") if self._cached.get(model.id, False) else _("Not downloaded"))
			self._list.SetItem(index, 5, _("Yes") if model.id == active else "")
		self._update_buttons()

	def _update_buttons(self) -> None:
		if self._delete_task is not None or self._status_task is not None:
			self._prepare.Disable()
			self._active.Disable()
			self._delete.Disable()
			return
		model = self._selected()
		self._prepare.Enable(model is not None)
		self._active.Enable(model is not None and model.id != get_embedding_model())
		self._delete.Enable(model is not None and self._cached.get(model.id, False) and model.id != get_embedding_model())

	def _on_active(self, _event: wx.CommandEvent) -> None:
		model = self._selected()
		if model is None:
			return
		try:
			set_embedding_model(model.id)
			self._refresh_rows()
		except Exception as error:
			error_reporter.report(
				error,
				ErrorContext(operation="set embedding model", model=model.id, origin="embedding model manager"),
				owner=lambda presentation: wx.MessageBox(
					presentation.message,
					presentation.title,
					wx.ICON_ERROR,
					parent=self,
				),
			)

	def _on_prepare(self, _event: wx.CommandEvent) -> None:
		model = self._selected()
		if model is None:
			return

		def worker(dialog: DownloadProgressDialog) -> None:
			embedding_model_service.prepare(model.id, progress=dialog.update_message, cancel_event=dialog.cancel_event)
			dialog.signal_complete(True, _("Embedding model is ready."))

		DownloadProgressDialog.run(self, _("Prepare Embedding Model"), worker, initial_message=_("Preparing model…"))
		self._refresh_catalog()

	def _on_delete(self, _event: wx.CommandEvent) -> None:
		model = self._selected()
		if model is None or model.id == get_embedding_model():
			return
		if wx.MessageBox(_("Delete the cached files for this embedding model?"), _("Confirm deletion"), wx.YES_NO | wx.ICON_QUESTION, parent=self) != wx.YES:
			return
		model_id = model.id
		self._delete_task = background_tasks.submit(
			lambda _cancel: embedding_model_service.delete(model_id),
			on_success=lambda _result: self._mark_deleted(model_id),
			on_error=lambda error: error_reporter.report(
				error,
				ErrorContext(operation="delete embedding model", model=model_id, origin="embedding model manager"),
				owner=lambda presentation: wx.MessageBox(
					presentation.message,
					presentation.title,
					wx.ICON_ERROR,
					parent=self,
				),
			),
			on_finally=self._finish_delete,
			is_alive=lambda: not self._destroyed,
		)
		self._update_buttons()

	def _mark_deleted(self, model_id: str) -> None:
		self._cached[model_id] = False

	def _finish_delete(self) -> None:
		self._delete_task = None
		if not self._destroyed:
			self._refresh_catalog()

	def _on_close(self, _event: wx.Event) -> None:
		self._destroyed = True
		if self._status_task is not None:
			self._status_task.cancel()
		if self._delete_task is not None:
			self._delete_task.detach()
		self.EndModal(wx.ID_CLOSE)


def open_embedding_model_dialog(parent: wx.Window) -> None:
	dialog = EmbeddingModelManagementDialog(parent)
	try:
		dialog.ShowModal()
	finally:
		dialog.Destroy()
