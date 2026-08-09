# -*- coding: utf-8 -*-
"""Model Configure dialog — per-model sampling parameters only.

Opened from the model manager for a **specific model** (provider and
model are passed in; the dialog never re-asks which provider or model
to configure).  Fields come from ``config.model_config.MODEL_CONFIG_FIELDS``
— the dialog is generic and data-driven, with no provider-ID branches.

The dialog answers *"how should this model generate responses?"*: it
pins context window, temperature, top-k, top-p, max tokens, and
repetition penalty for that model.  Saving pins **all** fields; the
"Reset to defaults" button removes the model's pinned entry entirely,
falling back to the provider's global settings.

Model availability, download, and active-model selection stay in the
model manager — this dialog never touches them.
"""

from __future__ import annotations

import builtins
from collections.abc import Callable
from typing import cast

import wx
from gui import guiHelper
from logHandler import log

from ..config.model_config import (
	MODEL_CONFIG_FIELDS,
	ModelFieldSpec,
	ModelSamplingConfig,
	clear_model_sampling,
	effective_field_value,
	model_configure_title,
	set_model_sampling,
)
from ..config.settings import build_provider_config


def _translate(message: str) -> str:
	return message


_ = cast(Callable[[str], str], getattr(builtins, "_", _translate))


def _base_sampling(provider_id: str) -> ModelSamplingConfig:
	"""Global fallback values for *provider_id* (from its YAML settings)."""
	config = build_provider_config(provider_id)
	return ModelSamplingConfig(
		num_ctx=config.num_ctx,
		temperature=config.generate_temperature,
		top_p=config.generate_top_p,
		max_tokens=config.generate_max_tokens,
	)


class ModelConfigureDialog(wx.Dialog):
	"""Generic per-model sampling configuration dialog."""

	def __init__(
		self,
		parent: wx.Window,
		provider_id: str,
		model_id: str,
		display_name: str,
	) -> None:
		super().__init__(
			parent,
			title=_(model_configure_title(display_name)),
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
		)
		self._provider_id = provider_id
		self._model_id = model_id
		self._display_name = display_name
		self._base = _base_sampling(provider_id)
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

		# TRANSLATORS: Label describing the sampling section of a model Configure dialog.
		section_label = wx.StaticText(
			self,
			label=_("Generation parameters for this model:"),
		)
		s_helper.addItem(section_label)

		for spec in MODEL_CONFIG_FIELDS:
			label = wx.StaticText(self, label=spec.label)
			s_helper.addItem(label)
			ctrl = wx.TextCtrl(self)
			s_helper.addItem(ctrl, flag=wx.EXPAND)
			self._controls[spec.id] = ctrl
			s_helper.sizer.AddSpacer(4)

		# TRANSLATORS: Note shown in the model Configure dialog explaining the pinned-only fields.
		hint_label = wx.StaticText(
			self,
			label=_(
				"Top-k and repetition penalty apply to local backends "
				"(Ollama, LiteRT-LM); cloud providers may ignore them."
			),
		)
		s_helper.addItem(hint_label)

		# ── Reset / Save / Cancel ─────────────────────────────────
		button_sizer = guiHelper.ButtonHelper(wx.HORIZONTAL)
		# TRANSLATORS: Button that clears a model's pinned sampling settings.
		button_sizer.addButton(self, wx.ID_RESET, label="")
		button_sizer.addButton(self, wx.ID_OK, label="")
		button_sizer.addButton(self, wx.ID_CANCEL, label="")
		self.Bind(wx.EVT_BUTTON, self._on_reset, id=wx.ID_RESET)
		self.Bind(wx.EVT_BUTTON, self._on_save, id=wx.ID_OK)
		self.Bind(wx.EVT_BUTTON, self._on_cancel, id=wx.ID_CANCEL)
		s_helper.addDialogDismissButtons(button_sizer, separated=True)

		self.SetSizer(main_sizer)
		main_sizer.Fit(self)
		self.SetMinSize(self.scaleSize((460, -1)))

	def scaleSize(self, size: tuple[int, int]) -> wx.Size:
		return wx.Size(*size)

	def _populate_fields(self) -> None:
		"""Fill each field with the current effective value."""
		for spec in MODEL_CONFIG_FIELDS:
			ctrl = self._controls.get(spec.id)
			if ctrl is None:
				continue
			value = effective_field_value(
				self._provider_id,
				self._model_id,
				self._base,
				spec.id,
			)
			ctrl.SetValue(_format_value(spec, value))

	# ------------------------------------------------------------------
	# Field access
	# ------------------------------------------------------------------

	def _read_spec_value(self, spec: ModelFieldSpec) -> int | float | None:
		ctrl = self._controls.get(spec.id)
		if ctrl is None:
			return None
		raw = ctrl.GetValue().strip()
		if not raw:
			return None
		try:
			if spec.kind == "int":
				return int(raw)
			return float(raw)
		except ValueError:
			return None

	def _draft_config(self) -> ModelSamplingConfig | None:
		"""Validate every field and build the config that would be saved.

		Returns ``None`` (after showing an accessible error) when any
		field is empty or invalid.
		"""
		values: dict[str, int | float] = {}
		for spec in MODEL_CONFIG_FIELDS:
			value = self._read_spec_value(spec)
			if value is None:
				wx.MessageBox(
					# TRANSLATORS: Error when a sampling field is empty or invalid; {label} is the field label.
					_("{} must be a valid number.").format(spec.label.rstrip(":")),
					_("Error"),
					wx.ICON_ERROR,
				)
				return None
			if spec.minimum is not None and value < spec.minimum:
				wx.MessageBox(
					# TRANSLATORS: Error when a sampling field is below its minimum; {label} is the field label and {minimum} the minimum value.
					_("{} must be at least {}.").format(spec.label.rstrip(":"), spec.minimum),
					_("Error"),
					wx.ICON_ERROR,
				)
				return None
			values[spec.id] = value
		return ModelSamplingConfig(**values)

	# ------------------------------------------------------------------
	# Event handlers
	# ------------------------------------------------------------------

	def _on_reset(self, _event: wx.CommandEvent) -> None:
		try:
			# Broad catch is deliberate: a store failure is logged and the
			# dialog stays usable with its current values.
			# pylint: disable=broad-exception-caught
			clear_model_sampling(self._provider_id, self._model_id)
		except Exception as exc:
			log.error(
				"Failed to clear model settings for %s/%s: %s",
				self._provider_id,
				self._model_id,
				exc,
			)
		self._populate_fields()

	def _on_save(self, _event: wx.CommandEvent) -> None:
		config = self._draft_config()
		if config is None:
			return
		try:
			# Broad catch is deliberate: a persistence failure is reported
			# to the user and the dialog stays open for correction.
			# pylint: disable=broad-exception-caught
			set_model_sampling(self._provider_id, self._model_id, config)
		except Exception as exc:
			log.error(
				"Failed to save model settings for %s/%s: %s",
				self._provider_id,
				self._model_id,
				exc,
			)
			wx.MessageBox(
				# TRANSLATORS: Error shown when saving model configuration fails; {error} is the reason.
				_("Failed to save model settings: {}").format(exc),
				_("Error"),
				wx.ICON_ERROR,
			)
			return
		self.EndModal(wx.ID_OK)

	def _on_cancel(self, _event: wx.CommandEvent) -> None:
		self.EndModal(wx.ID_CANCEL)


def _format_value(spec: ModelFieldSpec, value: int | float) -> str:
	"""Format *value* for display in a field of kind *spec.kind*."""
	if spec.kind == "int":
		return str(int(value))
	if isinstance(value, float) and value.is_integer():
		return str(int(value))
	return str(value)


def open_model_configure(
	parent: wx.Window,
	provider_id: str,
	model_id: str,
	display_name: str,
) -> None:
	"""Open the Configure dialog for *model_id* under *provider_id*.

	Modal: returns when the dialog is closed.
	"""
	dlg = ModelConfigureDialog(
		parent,
		provider_id,
		model_id,
		display_name,
	)
	try:
		dlg.ShowModal()
	finally:
		dlg.Destroy()


__all__ = ["ModelConfigureDialog", "open_model_configure"]
