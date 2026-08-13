# -*- coding: utf-8 -*-
"""Provider Configure dialogs — connection/runtime configuration only.

Each provider gets a dedicated Configure dialog whose fields come from
``providers.registry.get_configure_fields``.  The dialog answers the
question *"how do I connect to and configure this provider/runtime?"*.

It deliberately contains **no model fields**: model selection, model
download, and active-model handling belong to the provider-specific
model manager.  This is enforced structurally — the field registry has
no model-related field IDs — not merely by omitting widgets.  Think /
reasoning mode (a runtime behavior, not a model property) is offered
for the runtimes that support it.
"""

from __future__ import annotations

import builtins
from collections.abc import Callable
from typing import Any, cast

import wx
from gui import guiHelper
from gui.guiHelper import (
	LabeledControlHelper,
)
from logHandler import log

from ..config.settings import build_provider_config, set_openai_compat_config
from ..providers.adapters.openai_compat import OpenAICompatProvider
from ..providers.registry import (
	ConfigureFieldSpec,
	configure_dialog_title,
	get_configure_fields,
	get_provider_capabilities,
	is_installable,
	is_runtime_installed,
	provider_display_name,
)
from .task_runner import TaskHandle, background_tasks


def _translate(message: str) -> str:
	return message


_ = cast(Callable[[str], str], getattr(builtins, "_", _translate))


def build_configure_dialog(
	parent: wx.Window,
	provider_id: str,
	provider_name: str | None = None,
) -> "ProviderConfigureDialog":
	"""Construct the Configure dialog for *provider_id*."""
	return ProviderConfigureDialog(
		parent,
		provider_id,
		provider_name or provider_display_name(provider_id),
	)


class ProviderConfigureDialog(wx.Dialog):
	"""Generic provider configuration dialog driven by field specs."""

	def __init__(
		self,
		parent: wx.Window,
		provider_id: str,
		provider_name: str,
	) -> None:
		super().__init__(
			parent,
			title=_(configure_dialog_title(provider_name)),
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
		)
		self._provider_id = provider_id
		self._destroyed = False
		self._test_task: TaskHandle[tuple[bool, str]] | None = None
		self._provider_name = provider_name
		self._config = build_provider_config(provider_id)
		self._fields = get_configure_fields(provider_id)
		#: Per-field LabeledControlHelper keyed by spec.id.
		self._lch: dict[str, LabeledControlHelper] = {}
		self._secret_cbs: dict[str, wx.CheckBox] = {}

		self._build_ui()
		self._populate_fields()
		self.Bind(wx.EVT_CLOSE, self._on_close)

		# Keyboard routing: Enter triggers OK (save), Escape triggers Cancel.
		self.SetAffirmativeId(wx.ID_OK)
		self.SetEscapeId(wx.ID_CANCEL)
		# Intercept Enter in text fields to save the dialog (NVDA core pattern
		# from settingsDialogs._enterActivatesOk_ctrlSActivatesApply).
		self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

		self.CentreOnScreen()
		# Ensure initial focus lands on the first enabled text field.
		self._set_initial_focus()

	# ------------------------------------------------------------------
	# UI construction
	# ------------------------------------------------------------------

	def _build_ui(self) -> None:
		main_sizer = wx.BoxSizer(wx.VERTICAL)
		s_helper = guiHelper.BoxSizerHelper(self, sizer=main_sizer)

		if is_installable(self._provider_id):
			# TRANSLATORS: Label for the runtime installation status shown in a provider Configure dialog.
			runtime_label = wx.StaticText(self, label=_("Runtime status:"))
			s_helper.addItem(runtime_label)
			self._runtime_status = wx.StaticText(self, label="")
			s_helper.addItem(self._runtime_status)
			s_helper.sizer.AddSpacer(8)

		for spec in self._fields:
			self._add_field_row(s_helper, spec)
			s_helper.sizer.AddSpacer(4)

		caps = get_provider_capabilities(self._provider_id)
		if caps.think_config_key:
			# TRANSLATORS: Checkbox that enables think/reasoning mode for a provider runtime.
			self._think_cb = wx.CheckBox(
				self,
				label=_("Enable think/reasoning mode"),
			)
			s_helper.addItem(self._think_cb)

		s_helper.sizer.AddSpacer(8)

		# ── Test connection ────────────────────────────────────────
		# TRANSLATORS: Button that tests the provider connection from the Configure dialog.
		self._test_btn = wx.Button(self, label=_("Test Connection"))
		self._test_btn.Bind(wx.EVT_BUTTON, self._on_test_connection)
		s_helper.addItem(self._test_btn)

		# TRANSLATORS: Result of the provider connection test.
		self._test_result = wx.StaticText(self, label="")
		s_helper.addItem(self._test_result)

		# ── Save / Cancel ──────────────────────────────────────────
		button_sizer = guiHelper.ButtonHelper(wx.HORIZONTAL)
		button_sizer.addButton(self, wx.ID_OK, label="")
		button_sizer.addButton(self, wx.ID_CANCEL, label="")
		self.Bind(wx.EVT_BUTTON, self._on_save, id=wx.ID_OK)
		self.Bind(wx.EVT_BUTTON, self._on_cancel, id=wx.ID_CANCEL)
		s_helper.addDialogDismissButtons(button_sizer, separated=True)

		self.SetSizer(main_sizer)
		main_sizer.Fit(self)
		self.SetMinSize(self.scaleSize((520, -1)))

	def scaleSize(self, size: tuple[int, int]) -> wx.Size:
		return wx.Size(*size)

	def _add_field_row(self, s_helper: Any, spec: ConfigureFieldSpec) -> None:
		# Use NVDA's LabeledControlHelper so the label and control are
		# properly associated for screen readers and the label's
		# enabled/disabled state tracks the control.
		if spec.kind == "choice":
			items = list(spec.choices)
			if spec.default_choice and spec.default_choice not in items:
				items.insert(0, spec.default_choice)
			lch = LabeledControlHelper(
				self,
				spec.label,
				wx.Choice,
				choices=items,
			)
		elif spec.kind == "int":
			lch = LabeledControlHelper(
				self,
				spec.label,
				wx.SpinCtrl,
				min=0,
				max=64,
				initial=0,
			)
		else:
			style = wx.TE_PASSWORD if spec.secret else 0
			lch = LabeledControlHelper(self, spec.label, wx.TextCtrl, style=style)
		# TRANSLATORS: Accessible name suffix for provider config fields.
		lch.control.SetName(_("{} value").format(spec.label.rstrip(":")))
		s_helper.addItem(lch.sizer, flag=wx.EXPAND)
		self._lch[spec.id] = lch
		if spec.secret:
			# TRANSLATORS: Checkbox that reveals the API key in a provider Configure dialog.
			show_cb = wx.CheckBox(self, label=_("Show API key"))
			show_cb.Bind(
				wx.EVT_CHECKBOX,
				lambda event, field_id=spec.id: self._on_toggle_secret(field_id, event),
			)
			s_helper.addItem(show_cb)
			self._secret_cbs[spec.id] = show_cb

	def _populate_fields(self) -> None:
		"""Fill the fields from the persisted provider configuration."""
		values = {
			"api_key": str(getattr(self._config, "api_key", "") or ""),
			"base_url": str(getattr(self._config, "base_url", "") or ""),
			"server_url": str(getattr(self._config, "base_url", "") or ""),
			"chat_path": str(getattr(self._config, "chat_path", "") or ""),
			"backend": str(getattr(self._config, "litert_backend", "") or ""),
			"cache": str(getattr(self._config, "litert_cache", "") or ""),
			"cpu_thread_count": int(getattr(self._config, "litert_cpu_threads", 0) or 0),
		}
		for spec in self._fields:
			lch = self._lch.get(spec.id)
			if lch is None:
				continue
			value = values.get(spec.id, "")
			if spec.kind == "choice":
				selected = str(value or "")
				if selected in spec.choices:
					lch.control.SetStringSelection(selected)
				elif spec.default_choice:
					lch.control.SetStringSelection(spec.default_choice)
			elif spec.kind == "int":
				lch.control.SetValue(int(value))
			else:
				lch.control.SetValue(str(value or ""))

		if is_installable(self._provider_id):
			self._refresh_runtime_status()

		if hasattr(self, "_think_cb"):
			self._think_cb.Value = bool(getattr(self._config, "think", False))

	def _refresh_runtime_status(self) -> None:
		if is_runtime_installed(self._provider_id):
			# TRANSLATORS: Runtime installation status shown in the LiteRT-LM Configure dialog.
			self._runtime_status.SetLabel(_("Installed"))
		else:
			# TRANSLATORS: Runtime installation status shown in the LiteRT-LM Configure dialog.
			self._runtime_status.SetLabel(_("Not Installed"))

	# ------------------------------------------------------------------
	# Field access
	# ------------------------------------------------------------------

	def _draft_config(self) -> Any:
		"""Build the config that would be saved from the current field values."""
		values = {**vars(self._config), "provider": self._provider_id}
		field_to_attr = {
			"api_key": "api_key",
			"base_url": "base_url",
			"server_url": "base_url",
			"chat_path": "chat_path",
			"backend": "litert_backend",
			"cache": "litert_cache",
			"cpu_thread_count": "litert_cpu_threads",
		}
		for spec in self._fields:
			lch = self._lch.get(spec.id)
			if lch is None:
				continue
			attr = field_to_attr.get(spec.id)
			if attr is None:
				continue
			if spec.kind == "choice":
				selected = lch.control.GetStringSelection().strip()
				if spec.default_choice and selected == spec.default_choice:
					values[attr] = ""
				else:
					values[attr] = selected
			elif spec.kind == "int":
				values[attr] = int(lch.control.GetValue())
			else:
				values[attr] = lch.control.GetValue().strip()
		if hasattr(self, "_think_cb"):
			values["think"] = self._think_cb.Value
		return type(self._config)(**values)

	def _on_toggle_secret(self, field_id: str, event: wx.CommandEvent) -> None:
		lch = self._lch.get(field_id)
		if lch is None:
			return
		lch.control.SetWindowStyle(wx.TE_PASSWORD if not event.IsChecked() else 0)
		event.Skip()

	# ------------------------------------------------------------------
	# Test connection
	# ------------------------------------------------------------------

	def _on_test_connection(self, _event: wx.CommandEvent) -> None:
		self._test_btn.Disable()
		# TRANSLATORS: Message shown while a provider connection test is running.
		self._test_result.SetLabel(_("Testing connection..."))
		self.Layout()
		# Snapshot the current field values on the main thread: wx controls
		# must never be read from a worker thread.
		try:
			# Broad catch is deliberate: a malformed field value must not leave
			# the button permanently disabled.
			# pylint: disable=broad-exception-caught
			config = self._draft_config()
		except Exception as exc:
			log.error("Failed to build config for connection test: %s", exc)
			# TRANSLATORS: Error shown when a connection test cannot start; {error} is the reason.
			self._test_done(False, _("Connection test failed: {error}").format(error=exc))
			return
		self._test_task = background_tasks.submit(
			lambda _cancel: self._run_test(config),
			on_success=lambda result: self._test_done(*result),
			on_error=lambda error: self._test_done(
				False,
				_("{name} connection failed: {error}").format(name=self._provider_name, error=error),
			),
			is_alive=lambda: not self._destroyed,
		)

	def _run_test(self, config: Any) -> tuple[bool, str]:
		"""Run the blocking connection test; never touch wx from this method."""
		provider = OpenAICompatProvider(config)
		try:
			models = provider.list_models()
		finally:
			provider.close()
		count = len(models)
		message = _("{name} connection successful. Found {count} model(s).").format(
			name=self._provider_name,
			count=count,
		)
		return True, message

	def _test_done(self, _success: bool, message: str) -> None:
		self._test_task = None
		self._test_result.SetLabel(message)
		self._test_btn.Enable()
		self.Layout()

	# ------------------------------------------------------------------
	# Save / cancel
	# ------------------------------------------------------------------

	def _on_save(self, _event: wx.CommandEvent) -> None:
		for spec in self._fields:
			if not spec.required:
				continue
			lch = self._lch.get(spec.id)
			value = lch.control.GetValue().strip() if lch is not None else ""
			if not value:
				wx.MessageBox(
					# TRANSLATORS: Error shown when a required field is empty in a provider Configure dialog; {label} is the field label.
					_("{} cannot be empty.").format(spec.label.rstrip(":")),
					_("Error"),
					wx.ICON_ERROR,
				)
				return
		try:
			# Broad catch is deliberate: a persistence failure is reported to
			# the user and the dialog stays open for correction.
			# pylint: disable=broad-exception-caught
			set_openai_compat_config(self._draft_config(), activate=False)
		except Exception as exc:
			log.error("Failed to save configuration for %s: %s", self._provider_id, exc)
			wx.MessageBox(
				# TRANSLATORS: Error shown when saving provider configuration fails; {error} is the reason.
				_("Failed to save configuration: {}").format(exc),
				_("Error"),
				wx.ICON_ERROR,
			)
			return
		self._destroyed = True
		if self._test_task is not None:
			self._test_task.cancel()
		self.EndModal(wx.ID_OK)

	def _on_cancel(self, _event: wx.CommandEvent) -> None:
		self._destroyed = True
		if self._test_task is not None:
			self._test_task.cancel()
		self.EndModal(wx.ID_CANCEL)

	def _on_close(self, _event: wx.CloseEvent) -> None:
		self._destroyed = True
		if self._test_task is not None:
			self._test_task.cancel()
		self.EndModal(wx.ID_CANCEL)

	# ------------------------------------------------------------------
	# Keyboard handling
	# ------------------------------------------------------------------

	def _on_char_hook(self, evt: wx.KeyEvent) -> None:
		"""Intercept Enter in text fields to save the dialog.

		Follows the NVDA core pattern from
		``settingsDialogs._enterActivatesOk_ctrlSActivatesApply``:
		when Enter or NumPad Enter is pressed while a ``wx.TextCtrl``
		has focus, post a ``wx.ID_OK`` button click event so the dialog
		is saved.  All other keys are passed through normally.
		"""
		if evt.KeyCode in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
			focused = self.FindFocus()
			if isinstance(focused, wx.TextCtrl):
				cmd = wx.CommandEvent(wx.wxEVT_COMMAND_BUTTON_CLICKED, wx.ID_OK)
				self.ProcessEvent(cmd)
				return
		evt.Skip()

	def _set_initial_focus(self) -> None:
		"""Place keyboard focus on the first enabled text field.

		Called after CentreOnScreen so the dialog is visible before
		focus is assigned.  Falls back to the OK button when every
		field is disabled.
		"""
		for spec in self._fields:
			lch = self._lch.get(spec.id)
			if lch is not None and lch.control.IsEnabled():
				lch.control.SetFocus()
				return
		ok = self.FindWindowById(wx.ID_OK)
		if ok is not None:
			ok.SetFocus()
