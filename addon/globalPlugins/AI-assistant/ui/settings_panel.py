# -*- coding: utf-8 -*-
from pathlib import Path
from typing import Any

import addonHandler
import wx
from gui import guiHelper
from gui.settingsDialogs import SettingsPanel

from ..config import defaults
from ..config.settings import (
	build_provider_config,
	get_enabled_providers,
	get_image_format,
	get_image_max_side,
	get_image_quality,
	get_language,
	get_litert_think,
	get_ollama_think,
	get_progress_enabled,
	get_provider,
	get_request_metrics_log_path,
	get_request_metrics_logging_enabled,
	get_streaming_enabled,
	get_streaming_tone_enabled,
	get_timeout_seconds,
	set_enabled_providers,
	set_image_format,
	set_image_max_side,
	set_image_quality,
	set_language,
	set_litert_think,
	set_model_name,
	set_ollama_think,
	set_provider,
	set_request_metrics_log_path,
	set_request_metrics_logging_enabled,
	set_streaming_enabled,
	set_streaming_tone_enabled,
)
from ..providers.litert_models import recommended_models
from ..providers.registry import (
	PROVIDER_IDS,
	ProviderLifecycleState,
	get_provider_info,
	provider_display_name,
	provider_state_label,
)
from .enabled_models import EnabledModelsStore
from .provider_dialog import open_provider_dialog

addonHandler.initTranslation()


# This settings panel stores one attribute per wx control it builds — the
# standard NVDA settings-dialog pattern — so the attribute limit and the
# out-of-init assignment rule are waived (controls can only be created in
# makeSettings, where the sizer exists).
class AIAssistantSettingsPanel(SettingsPanel):  # pylint: disable=too-many-instance-attributes
	# pylint: disable=attribute-defined-outside-init
	# TRANSLATORS: Title shown at the top of the AI Assistant settings panel.
	title = _("AI Assistant")

	def makeSettings(self, settingsSizer):
		sHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)

		provider = get_provider()
		enabled = get_enabled_providers()

		# ── Enabled Providers ───────────────────────────────────────
		# TRANSLATORS: Section label for enabling/disabling AI providers.
		enabledGroupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Enabled Providers"))
		enabledGroupHelper = sHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=enabledGroupSizer))
		# TRANSLATORS: Label explaining the provider checkboxes.
		enabledGroupHelper.addItem(
			wx.StaticText(
				self,
				label=_("Select which AI providers are available for use:"),
			)
		)
		# TRANSLATORS: Checkbox label for enabling the Ollama provider.
		self.ollamaEnabledCheckbox = enabledGroupHelper.addItem(
			wx.CheckBox(self, label=_("Ollama")),
		)
		self.ollamaEnabledCheckbox.Value = "ollama" in enabled
		# TRANSLATORS: Checkbox label for enabling the Gemini provider.
		self.geminiEnabledCheckbox = enabledGroupHelper.addItem(
			wx.CheckBox(self, label=_("Gemini")),
		)
		self.geminiEnabledCheckbox.Value = "gemini" in enabled
		# TRANSLATORS: Checkbox label for enabling the OpenAI provider.
		self.openaiEnabledCheckbox = enabledGroupHelper.addItem(
			wx.CheckBox(self, label=_("OpenAI")),
		)
		self.openaiEnabledCheckbox.Value = "openai" in enabled
		# TRANSLATORS: Checkbox label for enabling the LiteRT-LM provider.
		self.litertEnabledCheckbox = enabledGroupHelper.addItem(
			wx.CheckBox(self, label=_("LiteRT-LM")),
		)
		self.litertEnabledCheckbox.Value = "litert-lm" in enabled
		# Wire up checkboxes to refresh provider dropdown
		for cb in (
			self.ollamaEnabledCheckbox,
			self.geminiEnabledCheckbox,
			self.openaiEnabledCheckbox,
			self.litertEnabledCheckbox,
		):
			cb.Bind(wx.EVT_CHECKBOX, self._on_enabled_provider_changed)

		# ── Active AI ───────────────────────────────────────────────
		# TRANSLATORS: Section label for the active provider/model selection.
		activeGroupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Active AI"))
		activeGroupHelper = sHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=activeGroupSizer))

		providerChoices = self._build_provider_choices()
		selectedProviderIndex = self._selected_provider_index(provider)

		# TRANSLATORS: Label for the active provider dropdown.
		activeGroupHelper.addItem(wx.StaticText(self, label=_("Active provider:")))
		self.providerChoice = wx.Choice(self, choices=providerChoices)
		self.providerChoice.SetSelection(max(selectedProviderIndex, 0))
		self.providerChoice.Bind(wx.EVT_CHOICE, self._on_provider_choice)
		activeGroupHelper.addItem(self.providerChoice)

		# TRANSLATORS: Label showing the active provider's status.
		self.providerStatusText = wx.StaticText(self, label="")
		activeGroupHelper.addItem(self.providerStatusText)

		# TRANSLATORS: Label for the active model dropdown.
		activeGroupHelper.addItem(wx.StaticText(self, label=_("Active model:")))
		self.modelCombo = wx.ComboBox(
			self,
			choices=[],
			style=wx.CB_DROPDOWN,
		)
		activeGroupHelper.addItem(self.modelCombo)

		# TRANSLATORS: Checkbox to enable think/reasoning mode for the active provider.
		self.thinkCheckbox = activeGroupHelper.addItem(
			wx.CheckBox(self, label=_("Enable think mode (active provider)")),
		)

		# TRANSLATORS: Button that opens the provider management dialog from the settings page.
		self.manageProvidersBtn = activeGroupHelper.addItem(
			wx.Button(self, label=_("&Manage AI Providers...")),
		)
		self.manageProvidersBtn.Bind(wx.EVT_BUTTON, self._on_manage_providers)

		# TRANSLATORS: Button that opens the Configure dialog for the active model.
		self.configureActiveModelBtn = activeGroupHelper.addItem(
			wx.Button(self, label=_("Configure Active &Model...")),
		)
		self.configureActiveModelBtn.Bind(wx.EVT_BUTTON, self._on_configure_active_model)

		# TRANSLATORS: Hint explaining where per-model generation settings are configured.
		activeGroupHelper.addItem(
			wx.StaticText(
				self,
				label=_(
					"Per-model generation settings (context window, temperature, "
					"top-k, top-p, and more) are configured from Manage AI Providers "
					"or the Configure Active Model button."
				),
			)
		)

		self.sharedGroupSizer = self._build_advanced_settings(sHelper)

		self._update_active_ai_state()

	def _add_labeled_text_ctrl(self, helper, label, initialValue):
		labelControl = wx.StaticText(self, label=label)
		textControl = wx.TextCtrl(self)
		textControl.Value = str(initialValue)
		helper.addItem(labelControl)
		helper.addItem(textControl)
		return textControl

	def _add_labeled_combo_box(self, helper, label, choices, selection):
		labelControl = wx.StaticText(self, label=label)
		comboBox = wx.ComboBox(self, choices=choices, style=wx.CB_READONLY)
		if selection in choices:
			comboBox.SetStringSelection(selection)
		elif choices:
			comboBox.SetSelection(0)
		helper.addItem(labelControl)
		helper.addItem(comboBox)
		return comboBox

	def _get_supported_prompt_language_options(self) -> list[tuple[str, str]]:
		template_dir = Path(__file__).resolve().parents[1] / "prompts" / "templates"
		# TRANSLATORS: Prompt language option that uses NVDA’s current UI language automatically.
		options = [(defaults.DEFAULT_LANGUAGE, _("Automatic (use NVDA language)"))]
		if not template_dir.exists():
			return options
		options.extend((child.name, child.name) for child in sorted(template_dir.iterdir()) if child.is_dir())
		return options

	def _get_prompt_language_label(self, language: str) -> str:
		for value, label in self._promptLanguageOptions:
			if value == language:
				return label
		return language

	def _get_prompt_language_value(self, label: str) -> str:
		for value, option_label in self._promptLanguageOptions:
			if option_label == label:
				return value
		return label

	# ------------------------------------------------------------------
	# Provider enable / disable + active AI helpers
	# ------------------------------------------------------------------

	def _build_provider_choices(self) -> list[str]:
		"""Return active-provider dropdown labels, filtered by enabled providers."""
		enabled = get_enabled_providers()
		return [provider_display_name(pid) for pid in PROVIDER_IDS if pid in enabled]

	def _selected_provider_index(self, provider: str) -> int:
		"""Return the dropdown index for *provider* in the filtered (enabled-only) list."""
		choices = self._build_provider_choices()
		for idx, label in enumerate(choices):
			if label == provider_display_name(provider):
				return idx
		return 0

	def _selected_provider_index(self, provider: str) -> int:
		"""Return the dropdown index for *provider* in the filtered (enabled-only) list."""
		choices = self._build_provider_choices()
		for idx, label in enumerate(choices):
			if label == provider_display_name(provider):
				return idx
		return 0

	def _on_enabled_provider_changed(self, _event: wx.CommandEvent) -> None:
		"""Refresh the provider dropdown when enable/disable checkboxes change."""
		current_provider = self._selected_provider()
		choices = self._build_provider_choices()
		self.providerChoice.Clear()
		self.providerChoice.AppendItems(choices)
		idx = self._selected_provider_index(current_provider)
		self.providerChoice.SetSelection(max(idx, 0))
		self._update_active_ai_state()

	# ------------------------------------------------------------------
	# Active AI state
	# ------------------------------------------------------------------

	def _selected_provider(self) -> str:
		index = self.providerChoice.GetSelection()
		if index < 0:
			return get_provider()
		choices = self._build_provider_choices()
		if index >= len(choices):
			return get_provider()
		selected_label = choices[index]
		for pid in PROVIDER_IDS:
			if provider_display_name(pid) == selected_label:
				return pid
		return get_provider()

	def _current_model_name(self, provider_id: str) -> str:
		try:
			# Broad catch is deliberate: the settings page must keep rendering
			# even if a provider's stored config cannot be read.
			# pylint: disable=broad-exception-caught
			return str(build_provider_config(provider_id).model_name or "").strip()
		except Exception:
			return ""

	def _model_choices_for(self, provider_id: str) -> list[str]:
		"""Return non-blocking model choices for the Active Model combo.

		Never performs network calls on the NVDA main thread: LiteRT-LM
		models come from the local catalog, and other providers offer
		the models previously enabled in their model manager plus the
		stored active model.
		"""
		choices: list[str] = []
		if provider_id == "litert-lm":
			choices.extend(m.model_id for m in recommended_models())
		try:
			# Broad catch is deliberate: the enabled-models store must never
			# break the settings page.
			# pylint: disable=broad-exception-caught
			enabled = EnabledModelsStore().get_enabled(provider_id)
			for model_id in enabled:
				if model_id not in choices:
					choices.append(model_id)
		except Exception:
			pass
		current = self._current_model_name(provider_id)
		if current and current not in choices:
			choices.insert(0, current)
		return choices

	def _refresh_active_model_choices(self, provider_id: str) -> None:
		choices = self._model_choices_for(provider_id)
		current = self._current_model_name(provider_id)
		self.modelCombo.Clear()
		self.modelCombo.AppendItems(choices)
		self.modelCombo.SetValue(current)

	def _refresh_provider_status(self, provider_id: str) -> None:
		info = get_provider_info(provider_id)
		state_label = provider_state_label(info.state)
		if info.state is ProviderLifecycleState.NOT_INSTALLED:
			# TRANSLATORS: Status message shown when the active provider is not installed; {state} is the state name.
			self.providerStatusText.SetLabel(
				_("Status: {state}. Use Manage AI Providers to install this provider.").format(
					state=state_label
				)
			)
		elif info.state is ProviderLifecycleState.AVAILABLE:
			# TRANSLATORS: Status message shown when the active provider is not yet configured; {state} is the state name.
			self.providerStatusText.SetLabel(
				_("Status: {state}. Use Manage AI Providers to configure this provider.").format(
					state=state_label
				)
			)
		else:
			# TRANSLATORS: Status message shown for the active provider; {state} is the state name.
			self.providerStatusText.SetLabel(
				_("Status: {state}.").format(state=state_label)
			)

	def _refresh_think_checkbox(self, provider_id: str) -> None:
		thinkable = provider_id in ("ollama", "litert-lm")
		self.thinkCheckbox.Enable(thinkable)
		if provider_id == "ollama":
			self.thinkCheckbox.Value = get_ollama_think()
		elif provider_id == "litert-lm":
			self.thinkCheckbox.Value = get_litert_think()
		else:
			self.thinkCheckbox.Value = False

	def _update_active_ai_state(self) -> None:
		provider = self._selected_provider()
		self._refresh_active_model_choices(provider)
		self._refresh_provider_status(provider)
		self._refresh_think_checkbox(provider)
		self.Layout()

	def _build_advanced_settings(self, parentHelper):
		# TRANSLATORS: Section label for shared runtime settings.
		groupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Shared Runtime Settings"))
		groupHelper = parentHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=groupSizer))
		# TRANSLATORS: Label for the request timeout setting.
		self.timeoutSecondsEdit = self._add_labeled_text_ctrl(
			groupHelper,
			_("Request timeout (seconds):"),
			str(
				get_timeout_seconds()
				if get_timeout_seconds() is not None
				else defaults.DEFAULT_TIMEOUT_SECONDS
			),
		)
		# TRANSLATORS: Checkbox label for request metrics logging.
		self.requestMetricsLoggingCheckbox = groupHelper.addItem(
			wx.CheckBox(self, label=_("Enable request metrics logging"))
		)
		self.requestMetricsLoggingCheckbox.Value = get_request_metrics_logging_enabled()
		# TRANSLATORS: Label for the metrics log file path setting.
		self.requestMetricsLogPathEdit = self._add_labeled_text_ctrl(
			groupHelper,
			_("Metrics log file path:"),
			get_request_metrics_log_path(),
		)
		# TRANSLATORS: Label for the prompt language chooser.
		self._promptLanguageOptions = self._get_supported_prompt_language_options()
		languageLabels = [label for _, label in self._promptLanguageOptions]
		currentLanguageLabel = self._get_prompt_language_label(get_language())
		self.promptLanguageChoice = self._add_labeled_combo_box(
			groupHelper,
			_("Prompt language:"),
			languageLabels,
			currentLanguageLabel,
		)
		# TRANSLATORS: Label for the image max side length setting.
		self.imageMaxSideEdit = self._add_labeled_text_ctrl(
			groupHelper,
			_("Image max side length (pixels):"),
			str(
				get_image_max_side() if get_image_max_side() is not None else defaults.DEFAULT_IMAGE_MAX_SIDE
			),
		)
		self.imageFormatChoice = wx.Choice(self, choices=["PNG", "JPEG"])
		self.imageFormatChoice.SetSelection(
			["PNG", "JPEG"].index(get_image_format()) if get_image_format() in {"PNG", "JPEG"} else 0
		)
		# TRANSLATORS: Label for the image format dropdown.
		groupHelper.addItem(wx.StaticText(self, label=_("Image format: ")))
		groupHelper.addItem(self.imageFormatChoice)
		# TRANSLATORS: Label for the JPEG quality setting.
		self.imageQualityEdit = self._add_labeled_text_ctrl(
			groupHelper,
			_("Image quality (JPEG only, 1-100):"),
			str(get_image_quality() if get_image_quality() is not None else defaults.DEFAULT_IMAGE_QUALITY),
		)
		# TRANSLATORS: Checkbox label for enabling streaming.
		self.streamingCheckbox = groupHelper.addItem(wx.CheckBox(self, label=_("Enable streaming")))
		# TRANSLATORS: Checkbox label for announcing progress.
		self.progressCheckbox = groupHelper.addItem(wx.CheckBox(self, label=_("Announce progress")))
		# TRANSLATORS: Checkbox label for streaming tone feedback.
		self.streamingToneCheckbox = groupHelper.addItem(
			wx.CheckBox(self, label=_("Enable streaming tone feedback"))
		)
		self.streamingCheckbox.Value = get_streaming_enabled()
		self.progressCheckbox.Value = get_progress_enabled()
		self.streamingToneCheckbox.Value = get_streaming_tone_enabled()
		return groupSizer

	def _show_error(self, message: str) -> None:
		# TRANSLATORS: Title of the generic error message dialog.
		wx.MessageBox(message, _("Error"), wx.ICON_ERROR)

	def _parse_int(self, field: wx.TextCtrl, message: str, minimum: int | None = None) -> int | None:
		raw = field.Value.strip()
		try:
			value = int(raw)
		except ValueError:
			self._show_error(message)
			return None
		if minimum is not None and value < minimum:
			self._show_error(message)
			return None
		return value

	def _parse_float(self, field: wx.TextCtrl, message: str, minimum: float | None = None) -> float | None:
		raw = field.Value.strip()
		try:
			value = float(raw)
		except ValueError:
			self._show_error(message)
			return None
		if minimum is not None and value < minimum:
			self._show_error(message)
			return None
		return value

	# onSave validates and persists every field in the panel; it is long by
	# design (one block per setting group) and is intentionally left
	# monolithic so the save order stays visible.
	def onSave(self):  # pylint: disable=too-many-locals,too-many-return-statements,too-many-branches,too-many-statements
		provider = self._selected_provider()

		# ── Collect enabled providers (deferred save until after validation) ──
		enabled = []
		if self.ollamaEnabledCheckbox.Value:
			enabled.append("ollama")
		if self.geminiEnabledCheckbox.Value:
			enabled.append("gemini")
		if self.openaiEnabledCheckbox.Value:
			enabled.append("openai")
		if self.litertEnabledCheckbox.Value:
			enabled.append("litert-lm")
		if not enabled:
			self._show_error(_("At least one provider must be enabled."))
			return

		# ── Validate selected provider is enabled ──
		if provider not in enabled:
			# TRANSLATORS: Error when the active provider has been disabled in settings.
			self._show_error(
				_(
					'The selected provider "{provider}" is currently disabled. '
					"Please enable it or select a different active provider."
				).format(provider=provider)
			)
			return

		# ── Active model validation ──
		model_name = self.modelCombo.GetValue().strip()
		if not model_name:
			# TRANSLATORS: Error when the active model name is empty.
			self._show_error(_("Active model name cannot be empty."))
			return

		# ── Shared field validation ──
		timeoutSeconds = self._parse_float(
			self.timeoutSecondsEdit,
			_("Timeout seconds must be a positive number."),
			minimum=0.000001,
		)
		if timeoutSeconds is None:
			return

		imageMaxSide = self._parse_int(
			self.imageMaxSideEdit,
			_("Image max side length must be an integer of at least 128."),
			minimum=128,
		)
		if imageMaxSide is None:
			return

		imageFormatIndex = self.imageFormatChoice.GetSelection()
		if imageFormatIndex < 0 or imageFormatIndex >= 2:
			self._show_error(_("Image format must be PNG or JPEG."))
			return
		imageFormat = ["PNG", "JPEG"][imageFormatIndex]

		imageQuality = self._parse_int(
			self.imageQualityEdit,
			_("Image quality must be an integer between 1 and 100."),
			minimum=1,
		)
		if imageQuality is None or imageQuality > 100:
			self._show_error(_("Image quality must be an integer between 1 and 100."))
			return

		requestMetricsLoggingEnabled = self.requestMetricsLoggingCheckbox.Value
		requestMetricsLogPath = self.requestMetricsLogPathEdit.Value.strip()
		if requestMetricsLoggingEnabled and not requestMetricsLogPath:
			self._show_error(_("Metrics log file path cannot be empty when logging is enabled."))
			return

		# ── All validation passed; persist everything ──
		set_enabled_providers(enabled)
		set_provider(provider)
		set_model_name(model_name)
		if provider == "ollama":
			set_ollama_think(self.thinkCheckbox.Value)
		elif provider == "litert-lm":
			set_litert_think(self.thinkCheckbox.Value)

		set_image_max_side(imageMaxSide)
		set_image_format(imageFormat)
		set_image_quality(imageQuality)
		set_request_metrics_logging_enabled(requestMetricsLoggingEnabled)
		set_request_metrics_log_path(requestMetricsLogPath)
		if hasattr(self, "promptLanguageChoice"):
			prompt_language_label = self.promptLanguageChoice.GetStringSelection()
			prompt_language_value = self._get_prompt_language_value(prompt_language_label)
		else:
			prompt_language_value = get_language()
		set_language(prompt_language_value)
		set_streaming_enabled(self.streamingCheckbox.Value)
		set_streaming_tone_enabled(self.streamingToneCheckbox.Value)

	def _on_provider_choice(self, _event: Any) -> None:
		self._update_active_ai_state()

	def _on_manage_providers(self, _event: wx.CommandEvent) -> None:
		"""Open the provider management dialog, then refresh the active AI state."""
		open_provider_dialog(self)
		self._update_active_ai_state()

	def _on_configure_active_model(self, _event: wx.CommandEvent) -> None:
		"""Open the per-model Configure dialog for the active model."""
		provider = self._selected_provider()
		model_name = self.modelCombo.GetValue().strip()
		if not model_name:
			# TRANSLATORS: Error when the active model combo is empty.
			self._show_error(_("Select a model to configure first."))
			return
		from .model_config_dialog import open_model_configure

		open_model_configure(self, provider, model_name, model_name)
