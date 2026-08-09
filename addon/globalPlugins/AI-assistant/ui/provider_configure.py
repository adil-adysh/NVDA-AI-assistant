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
import threading
from collections.abc import Callable
from typing import Any, cast

import wx
from gui import guiHelper
from logHandler import log

from ..config.settings import build_provider_config, set_openai_compat_config
from ..providers.adapters.openai_compat import OpenAICompatProvider
from ..providers.registry import (
	ConfigureFieldSpec,
	configure_dialog_title,
	get_configure_fields,
	is_installable,
	is_runtime_installed,
	provider_display_name,
)


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

	#: Providers whose runtime supports think/reasoning mode.
	_THINKABLE_PROVIDERS = frozenset({"ollama", "litert-lm"})

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
		self._provider_name = provider_name
		self._config = build_provider_config(provider_id)
		self._fields = get_configure_fields(provider_id)
		self._controls: dict[str, wx.TextCtrl] = {}

		self._build_ui()
		self._populate_fields()
		self.CentreOnScreen()

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

		if self._provider_id in self._THINKABLE_PROVIDERS:
			# TRANSLATORS: Checkbox that enables think/reasoning mode for a provider runtime.
			self._think_cb = wx.CheckBox(
				self,
				label=_("Enable think/reasoning mode"),
			)
			s_helper.addItem(self._think_cb)

		s_helper.sizer.AddSpacer(8)

		# ── Test connection ────────────────────────────────────────
		# TRANSLATORS: Button that tests the provider connection from the Configure dialog.
		self._test_btn = wx.Button(self, label=_("&Test Connection"))
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
		label = wx.StaticText(self, label=spec.label)
		s_helper.addItem(label)
		ctrl = wx.TextCtrl(self, style=(wx.TE_PASSWORD if spec.secret else 0))
		s_helper.addItem(ctrl, flag=wx.EXPAND)
		self._controls[spec.id] = ctrl
		if spec.secret:
			# TRANSLATORS: Checkbox that reveals the API key in a provider Configure dialog.
			show_cb = wx.CheckBox(self, label=_("Show API key"))
			show_cb.Bind(
				wx.EVT_CHECKBOX,
				lambda event: self._on_toggle_secret(spec.id, event),
			)
			s_helper.addItem(show_cb)

	def _populate_fields(self) -> None:
		"""Fill the fields from the persisted provider configuration."""
		values = {
			"api_key": str(getattr(self._config, "api_key", "") or ""),
			"base_url": str(getattr(self._config, "base_url", "") or ""),
			"server_url": str(getattr(self._config, "base_url", "") or ""),
			"chat_path": str(getattr(self._config, "chat_path", "") or ""),
		}
		for spec in self._fields:
			ctrl = self._controls.get(spec.id)
			if ctrl is not None:
				ctrl.SetValue(values.get(spec.id, ""))

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
		}
		for spec in self._fields:
			ctrl = self._controls.get(spec.id)
			if ctrl is None:
				continue
			attr = field_to_attr.get(spec.id)
			if attr is not None:
				values[attr] = ctrl.GetValue().strip()
		if hasattr(self, "_think_cb"):
			values["think"] = self._think_cb.Value
		return type(self._config)(**values)

	def _on_toggle_secret(self, field_id: str, event: wx.CommandEvent) -> None:
		ctrl = self._controls.get(field_id)
		if ctrl is None:
			return
		ctrl.SetWindowStyle(wx.TE_PASSWORD if not event.IsChecked() else 0)
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
		thread = threading.Thread(target=self._run_test, args=(config,), daemon=True)
		thread.start()

	def _run_test(self, config: Any) -> None:
		"""Run the connection test off the main thread and report the result."""
		try:
			# Broad catch is deliberate: a connection test must always report
			# an accessible result instead of crashing the background thread.
			# pylint: disable=broad-exception-caught
			provider = OpenAICompatProvider(config)
			try:
				models = provider.list_models()
			finally:
				provider.close()
			count = len(models)
			# TRANSLATORS: Successful provider connection test result; {name} is the provider name and {count} the number of models found.
			message = _(
				"{name} connection successful. Found {count} model(s)."
			).format(name=self._provider_name, count=count)
			wx.CallAfter(self._test_done, True, message)
		except Exception as exc:
			log.debug("Connection test failed for %s: %s", self._provider_id, exc)
			# TRANSLATORS: Failed provider connection test result; {name} is the provider name and {error} the reason.
			message = _("{name} connection failed: {error}").format(
				name=self._provider_name,
				error=exc,
			)
			wx.CallAfter(self._test_done, False, message)

	def _test_done(self, _success: bool, message: str) -> None:
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
			ctrl = self._controls.get(spec.id)
			value = ctrl.GetValue().strip() if ctrl is not None else ""
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
		self.EndModal(wx.ID_OK)

	def _on_cancel(self, _event: wx.CommandEvent) -> None:
		self.EndModal(wx.ID_CANCEL)
