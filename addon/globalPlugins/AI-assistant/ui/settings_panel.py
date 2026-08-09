# -*- coding: utf-8 -*-
import threading
from pathlib import Path
from typing import Any

import addonHandler
import wx
from gui import guiHelper
from gui.settingsDialogs import SettingsPanel
from logHandler import log

from ..config import defaults
from ..config.settings import (
	get_enabled_providers,
	get_gemini_api_key,
	get_gemini_base_url,
	get_gemini_model_name,
	get_generate_max_tokens,
	get_generate_presence_penalty,
	get_generate_temperature,
	get_generate_top_k,
	get_generate_top_p,
	get_image_format,
	get_image_max_side,
	get_image_quality,
	get_language,
	get_litert_model_name,
	get_litert_server_url,
	get_max_retries,
	get_num_ctx,
	get_ollama_model_name,
	get_ollama_server_url,
	get_ollama_think,
	get_openai_api_key,
	get_openai_base_url,
	get_openai_model_name,
	get_progress_enabled,
	get_provider,
	get_request_metrics_log_path,
	get_request_metrics_logging_enabled,
	get_retry_backoff_seconds,
	get_streaming_enabled,
	get_streaming_tone_enabled,
	get_timeout_seconds,
	set_enabled_providers,
	set_image_format,
	set_image_max_side,
	set_image_quality,
	set_language,
	set_openai_compat_config,
	set_request_metrics_log_path,
	set_request_metrics_logging_enabled,
	set_streaming_enabled,
	set_streaming_tone_enabled,
)
from ..providers.config import OpenAICompatConfig
from ..providers.runtime.server import get_litert_supervisor

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

		# ── Active Provider ─────────────────────────────────────────
		# TRANSLATORS: Provider option label for Ollama.
		# TRANSLATORS: Provider option label for Gemini.
		self._providerOptions = [
			("ollama", _("Ollama")),
			("gemini", _("Gemini")),
			("openai", _("OpenAI")),
			("litert-lm", _("LiteRT-LM")),
		]
		providerChoices = self._build_provider_choices()
		selectedProviderIndex = self._selected_provider_index(provider)

		# TRANSLATORS: Section label for provider selection.
		providerGroupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Provider"))
		providerGroupHelper = sHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=providerGroupSizer))
		# TRANSLATORS: Label for the LLM provider dropdown.
		providerGroupHelper.addItem(wx.StaticText(self, label=_("LLM provider:")))
		self.providerChoice = wx.Choice(self, choices=providerChoices)
		self.providerChoice.SetSelection(max(selectedProviderIndex, 0))
		self.providerChoice.Bind(wx.EVT_CHOICE, self._on_provider_choice)
		providerGroupHelper.addItem(self.providerChoice)

		self.ollamaGroupSizer = self._build_ollama_settings(sHelper)
		self.geminiGroupSizer = self._build_gemini_settings(sHelper)
		self.openaiGroupSizer = self._build_openai_settings(sHelper)
		self.litertGroupSizer = self._build_litert_settings(sHelper)
		self.sharedGroupSizer = self._build_advanced_settings(sHelper)
		self.ollamaExpertGroupSizer = self._build_ollama_expert_settings(sHelper)
		self._build_expert_settings(sHelper)

		self._update_provider_field_state()

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

	def _build_ollama_settings(self, parentHelper):
		# TRANSLATORS: Section label for Ollama-specific settings.
		groupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Ollama Settings"))
		groupHelper = parentHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=groupSizer))
		# TRANSLATORS: Label for the Ollama model name setting.
		self.ollamaModelNameEdit = self._add_labeled_text_ctrl(
			groupHelper,
			_("Ollama model name:"),
			get_ollama_model_name(),
		)
		# TRANSLATORS: Label for the Ollama server URL setting.
		self.ollamaServerUrlEdit = self._add_labeled_text_ctrl(
			groupHelper,
			_("Ollama server URL:"),
			get_ollama_server_url(),
		)
		# TRANSLATORS: Label for the Ollama context window size setting.
		self.ollamaNumCtxEdit = self._add_labeled_text_ctrl(
			groupHelper,
			_("Context window size (may affect performance):"),
			str(get_num_ctx() if get_num_ctx() is not None else defaults.DEFAULT_NUM_CTX),
		)
		return groupSizer

	def _build_gemini_settings(self, parentHelper):
		# TRANSLATORS: Section label for Gemini-specific settings.
		groupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Gemini Settings"))
		groupHelper = parentHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=groupSizer))
		# TRANSLATORS: Label for the Gemini model name setting.
		self.geminiModelNameEdit = self._add_labeled_text_ctrl(
			groupHelper,
			_("Gemini model name:"),
			get_gemini_model_name(),
		)
		# TRANSLATORS: Label for the Gemini API key setting.
		self.geminiApiKeyEdit = self._add_labeled_text_ctrl(
			groupHelper,
			_("Gemini API key:"),
			get_gemini_api_key(),
		)
		# TRANSLATORS: Label for the Gemini base URL setting.
		self.geminiBaseUrlEdit = self._add_labeled_text_ctrl(
			groupHelper,
			_("Gemini base URL:"),
			get_gemini_base_url(),
		)
		return groupSizer

	def _build_openai_settings(self, parentHelper):
		# TRANSLATORS: Section label for OpenAI settings.
		groupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("OpenAI Settings"))
		groupHelper = parentHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=groupSizer))
		self.openaiModelNameEdit = self._add_labeled_text_ctrl(
			groupHelper,
			_("OpenAI model name:"),
			get_openai_model_name(),
		)
		self.openaiApiKeyEdit = self._add_labeled_text_ctrl(
			groupHelper,
			_("OpenAI API key:"),
			get_openai_api_key() or "",
		)
		self.openaiBaseUrlEdit = self._add_labeled_text_ctrl(
			groupHelper,
			_("OpenAI base URL:"),
			get_openai_base_url(),
		)
		return groupSizer

	def _build_litert_settings(self, parentHelper):
		# TRANSLATORS: Section label for LiteRT-LM-specific settings.
		groupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("LiteRT-LM Settings"))
		groupHelper = parentHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=groupSizer))
		# TRANSLATORS: Label for the LiteRT-LM model name setting.
		self.litertModelNameEdit = self._add_labeled_text_ctrl(
			groupHelper,
			_("LiteRT-LM model name:"),
			get_litert_model_name(),
		)
		# TRANSLATORS: Label for the LiteRT-LM server URL setting.
		self.litertServerUrlEdit = self._add_labeled_text_ctrl(
			groupHelper,
			_("LiteRT-LM server URL:"),
			get_litert_server_url(),
		)
		# TRANSLATORS: Label for the LiteRT-LM context window size setting.
		self.litertNumCtxEdit = self._add_labeled_text_ctrl(
			groupHelper,
			_("LiteRT-LM context window size (may affect performance):"),
			str(get_num_ctx()),
		)

		# ── Runtime installation status ─────────────────────────
		# TRANSLATORS: Section label for the LiteRT-LM runtime installation status.
		groupHelper.addItem(
			wx.StaticText(
				self,
				label=_("Runtime installation:"),
			)
		)
		self.litertRuntimeStatus = wx.StaticText(self, label="")
		groupHelper.addItem(self.litertRuntimeStatus)
		# TRANSLATORS: Button to download and install the LiteRT-LM runtime.
		self.litertDownloadBtn = wx.Button(self, label=_("&Download LiteRT-LM Runtime..."))
		self.litertDownloadBtn.Bind(wx.EVT_BUTTON, self._on_download_litert_runtime)
		groupHelper.addItem(self.litertDownloadBtn)
		# TRANSLATORS: Label for download progress during LiteRT-LM runtime installation.
		self.litertProgressLabel = wx.StaticText(self, label="")
		self.litertProgressLabel.Hide()
		groupHelper.addItem(self.litertProgressLabel)
		self.litertProgressGauge = wx.Gauge(self, range=100, size=(-1, 20))
		self.litertProgressGauge.Hide()
		groupHelper.addItem(self.litertProgressGauge, flag=wx.EXPAND)

		self._refresh_litert_runtime_status()
		return groupSizer

	# ------------------------------------------------------------------
	# Provider enable / disable helpers
	# ------------------------------------------------------------------

	def _build_provider_choices(self) -> list[str]:
		"""Return provider dropdown labels, filtered by enabled providers."""
		enabled = get_enabled_providers()
		return [label for value, label in self._providerOptions if value in enabled]

	def _selected_provider_index(self, provider: str) -> int:
		"""Return the dropdown index for *provider* in the filtered (enabled-only) list."""
		enabled = get_enabled_providers()
		filtered = [(v, label) for v, label in self._providerOptions if v in enabled]
		for idx, (value, _label) in enumerate(filtered):
			if value == provider:
				return idx
		return 0

	def _on_enabled_provider_changed(self, event: wx.CommandEvent) -> None:
		"""Refresh the provider dropdown when enable/disable checkboxes change."""
		current_provider = self._selected_provider()
		choices = self._build_provider_choices()
		self.providerChoice.Clear()
		self.providerChoice.AppendItems(choices)
		idx = self._selected_provider_index(current_provider)
		self.providerChoice.SetSelection(max(idx, 0))
		self._update_provider_field_state()

	# ------------------------------------------------------------------
	# LiteRT runtime download
	# ------------------------------------------------------------------

	def _refresh_litert_runtime_status(self) -> None:
		"""Update the LiteRT runtime status label and download button state."""
		supervisor = get_litert_supervisor()
		if supervisor.is_installed:
			# TRANSLATORS: Status message when the LiteRT-LM runtime is already installed.
			self.litertRuntimeStatus.SetLabel(_("Runtime is installed and ready."))
			self.litertDownloadBtn.Disable()
		else:
			# TRANSLATORS: Status message when the LiteRT-LM runtime is not yet installed.
			self.litertRuntimeStatus.SetLabel(
				_("Runtime is not installed. Download required to use LiteRT-LM.")
			)
			# Enable download only when litert-lm is the selected provider.
			is_litert = self._selected_provider() == "litert-lm"
			self.litertDownloadBtn.Enable(is_litert)

	def _on_download_litert_runtime(self, event: wx.CommandEvent) -> None:
		"""Download and extract the LiteRT-LM runtime in a background thread."""
		self.litertDownloadBtn.Disable()
		# TRANSLATORS: Progress message shown while the LiteRT-LM runtime is downloading.
		self.litertProgressLabel.SetLabel(_("Downloading LiteRT-LM runtime..."))
		self.litertProgressLabel.Show()
		self.litertProgressGauge.SetValue(0)
		self.litertProgressGauge.SetRange(100)
		self.litertProgressGauge.Show()
		self.Layout()

		def worker() -> None:
			supervisor = get_litert_supervisor()
			try:

				def progress(msg: str) -> None:
					wx.CallAfter(self.litertProgressLabel.SetLabel, msg)

				def bytes_progress(downloaded: int, total: int) -> None:
					wx.CallAfter(self._on_litert_bytes_progress, downloaded, total)

				supervisor.install(
					on_progress=progress,
					on_bytes_progress=bytes_progress,
				)
				wx.CallAfter(self._on_litert_download_complete, True, "")
			except Exception as exc:
				log.error("LiteRT runtime download failed: %s", exc)
				# TRANSLATORS: Error message when the LiteRT-LM runtime download fails.
				err_msg = _("Download failed: {}").format(exc)
				wx.CallAfter(self._on_litert_download_complete, False, err_msg)

		thread = threading.Thread(target=worker, daemon=True)
		thread.start()

	def _on_litert_bytes_progress(self, downloaded: int, total: int) -> None:
		"""Update the progress gauge from byte-level progress."""
		if total and total > 0:
			pct = min(downloaded * 100 // total, 100)
			if self.litertProgressGauge.GetRange() != 100:
				self.litertProgressGauge.SetRange(100)
			self.litertProgressGauge.SetValue(pct)
		else:
			# Indeterminate: pulse the gauge
			val = self.litertProgressGauge.GetValue()
			self.litertProgressGauge.SetValue(0 if val >= 100 else val + 5)

	def _on_litert_download_complete(self, success: bool, error_msg: str) -> None:
		"""Handle completion of the LiteRT runtime download."""
		self.litertProgressLabel.Hide()
		self.litertProgressGauge.Hide()
		if success:
			self._refresh_litert_runtime_status()
		else:
			self.litertDownloadBtn.Enable()
			self.litertProgressLabel.SetLabel(error_msg)
			self.litertProgressLabel.Show()
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

	def _build_ollama_expert_settings(self, parentHelper):
		# TRANSLATORS: Section label for experimental Ollama expert settings.
		groupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Ollama Expert Settings (Experimental)"))
		groupHelper = parentHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=groupSizer))
		# TRANSLATORS: Label for the Ollama repetition penalty setting.
		self.presencePenaltyEdit = self._add_labeled_text_ctrl(
			groupHelper,
			_("Repetition penalty:"),
			str(
				get_generate_presence_penalty()
				if get_generate_presence_penalty() is not None
				else defaults.DEFAULT_GENERATE_PRESENCE_PENALTY
			),
		)
		# TRANSLATORS: Checkbox label for enabling Ollama think mode.
		self.ollamaThinkCheckbox = groupHelper.addItem(wx.CheckBox(self, label=_("Enable Ollama think mode")))
		self.ollamaThinkCheckbox.Value = get_ollama_think()
		return groupSizer

	def _build_expert_settings(self, parentHelper):
		# TRANSLATORS: Section label for general experimental settings.
		groupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Expert Settings (Experimental)"))
		groupHelper = parentHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=groupSizer))
		# TRANSLATORS: Label for the response creativity temperature setting.
		self.temperatureEdit = self._add_labeled_text_ctrl(
			groupHelper,
			_("Response creativity (temperature):"),
			str(
				get_generate_temperature()
				if get_generate_temperature() is not None
				else defaults.DEFAULT_GENERATE_TEMPERATURE
			),
		)
		# TRANSLATORS: Label for the Top-k sampling setting.
		self.topKEdit = self._add_labeled_text_ctrl(
			groupHelper,
			_("Top-k sampling:"),
			str(
				get_generate_top_k() if get_generate_top_k() is not None else defaults.DEFAULT_GENERATE_TOP_K
			),
		)
		# TRANSLATORS: Label for the Top-p sampling setting.
		self.topPEdit = self._add_labeled_text_ctrl(
			groupHelper,
			_("Top-p sampling:"),
			str(
				get_generate_top_p() if get_generate_top_p() is not None else defaults.DEFAULT_GENERATE_TOP_P
			),
		)
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
	# design (one block per provider/setting) and is intentionally left
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

		# ── Validate LiteRT runtime when litert-lm is selected ──
		if provider == "litert-lm":
			supervisor = get_litert_supervisor()
			if not supervisor.is_installed:
				# TRANSLATORS: Warning when LiteRT-LM is selected but runtime not installed.
				self._show_error(
					_(
						"LiteRT-LM is selected but the runtime is not installed. "
						"Please download the runtime before selecting this provider."
					)
				)
				return

		# ── Provider-specific field validation & extraction ──
		model_name = ""
		base_url = ""
		api_key = ""
		num_ctx: int = get_num_ctx()
		think_value: bool = False

		if provider == "ollama":
			model_name = self.ollamaModelNameEdit.Value.strip()
			base_url = self.ollamaServerUrlEdit.Value.strip()
			if not model_name:
				self._show_error(_("Ollama model name cannot be empty"))
				return
			if not base_url:
				self._show_error(_("Ollama server URL cannot be empty."))
				return
			ollamaNumCtx = self._parse_int(
				self.ollamaNumCtxEdit,
				_("Context window size must be an integer of at least 256."),
				minimum=256,
			)
			if ollamaNumCtx is None:
				return
			num_ctx = ollamaNumCtx
			think_widget = getattr(self, "ollamaThinkCheckbox", None)
			think_value = think_widget.Value if think_widget is not None else False

		elif provider == "gemini":
			model_name = self.geminiModelNameEdit.Value.strip()
			base_url = self.geminiBaseUrlEdit.Value.strip()
			api_key = self.geminiApiKeyEdit.Value.strip()
			if not model_name:
				self._show_error(_("Gemini model name cannot be empty"))
				return
			if not api_key:
				self._show_error(_("Gemini API key cannot be empty"))
				return
			if not base_url:
				self._show_error(_("Gemini base URL cannot be empty."))
				return

		elif provider == "openai":
			model_name = self.openaiModelNameEdit.Value.strip()
			base_url = self.openaiBaseUrlEdit.Value.strip()
			api_key = self.openaiApiKeyEdit.Value.strip()
			if not model_name:
				self._show_error(_("OpenAI model name cannot be empty"))
				return
			if not api_key:
				self._show_error(_("OpenAI API key cannot be empty"))
				return
			if not base_url:
				self._show_error(_("OpenAI base URL cannot be empty."))
				return

		else:  # litert-lm
			model_name = self.litertModelNameEdit.Value.strip()
			base_url = self.litertServerUrlEdit.Value.strip()
			if not model_name:
				self._show_error(_("LiteRT-LM model name cannot be empty"))
				return
			litertNumCtx = self._parse_int(
				self.litertNumCtxEdit,
				_("Context window size must be an integer of at least 256."),
				minimum=256,
			)
			if litertNumCtx is None:
				return
			num_ctx = litertNumCtx

		# ── Shared field validation ──
		timeoutSeconds = self._parse_float(
			self.timeoutSecondsEdit,
			_("Timeout seconds must be a positive number."),
			minimum=0.000001,
		)
		if timeoutSeconds is None:
			return

		temperature = self._parse_float(
			self.temperatureEdit,
			_("Generate temperature must be a non-negative number."),
			minimum=0.0,
		)
		if temperature is None:
			return

		topK = self._parse_int(
			self.topKEdit,
			_("Top-k sampling must be a non-negative integer."),
			minimum=0,
		)
		if topK is None:
			return

		topP = self._parse_float(
			self.topPEdit,
			_("Top-p sampling must be a non-negative number."),
			minimum=0.0,
		)
		if topP is None:
			return

		maxTokens = get_generate_max_tokens()

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

		config = OpenAICompatConfig(
			provider=provider,
			model_name=model_name,
			base_url=base_url,
			api_key=api_key,
			timeout_seconds=timeoutSeconds,
			enable_progress=self.progressCheckbox.Value,
			num_ctx=num_ctx,
			max_retries=get_max_retries(),
			retry_backoff_seconds=get_retry_backoff_seconds(),
			generate_temperature=temperature,
			generate_top_k=topK,
			generate_top_p=topP,
			generate_max_tokens=maxTokens,
			think=think_value,
		)
		set_openai_compat_config(config)

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

	def _selected_provider(self) -> str:
		index = self.providerChoice.GetSelection()
		if index < 0:
			return "ollama"
		choices = self._build_provider_choices()
		if index >= len(choices):
			return "ollama"
		# Map through the filtered list to find the provider value
		selected_label = choices[index]
		for value, label in self._providerOptions:
			if label == selected_label:
				return value
		return "ollama"

	def _on_provider_choice(self, event: Any) -> None:
		self._update_provider_field_state()

	def _update_provider_field_state(self) -> None:
		provider = self._selected_provider()
		is_ollama = provider == "ollama"
		is_gemini = provider == "gemini"
		is_openai = provider == "openai"
		is_litert = provider == "litert-lm"

		self.ollamaGroupSizer.ShowItems(is_ollama)
		self.geminiGroupSizer.ShowItems(is_gemini)
		self.openaiGroupSizer.ShowItems(is_openai)
		self.litertGroupSizer.ShowItems(is_litert)
		self.ollamaExpertGroupSizer.ShowItems(is_ollama)

		self.ollamaModelNameEdit.Enable(is_ollama)
		self.ollamaServerUrlEdit.Enable(is_ollama)
		self.ollamaNumCtxEdit.Enable(is_ollama)
		self.geminiModelNameEdit.Enable(is_gemini)
		self.geminiApiKeyEdit.Enable(is_gemini)
		self.geminiBaseUrlEdit.Enable(is_gemini)
		self.openaiModelNameEdit.Enable(is_openai)
		self.openaiApiKeyEdit.Enable(is_openai)
		self.openaiBaseUrlEdit.Enable(is_openai)
		self.litertModelNameEdit.Enable(is_litert)
		self.litertServerUrlEdit.Enable(is_litert)
		self.litertNumCtxEdit.Enable(is_litert)
		self.presencePenaltyEdit.Enable(is_ollama)
		self.ollamaThinkCheckbox.Enable(is_ollama)

		# Only enable download button when litert is selected AND runtime not installed.
		if is_litert:
			supervisor = get_litert_supervisor()
			self.litertDownloadBtn.Enable(not supervisor.is_installed)
		else:
			self.litertDownloadBtn.Enable(False)

		self.Layout()
