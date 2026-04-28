# -*- coding: utf-8 -*-
import addonHandler
import wx
from pathlib import Path
from typing import Any

from gui import guiHelper
from gui.settingsDialogs import SettingsPanel

from ..config import defaults
from ..config.settings import (
    get_generate_presence_penalty,
    get_generate_top_k,
    get_generate_top_p,
    get_generate_temperature,
    get_gemini_config,
    get_image_format,
    get_image_quality,
    get_image_max_side,
    get_keep_alive,
    get_language,
    get_max_retries,
    get_num_ctx,
    get_progress_enabled,
    get_provider,
    get_ollama_config,
    get_request_metrics_log_path,
    get_request_metrics_logging_enabled,
    get_retry_backoff_seconds,
    get_streaming_enabled,
    get_timeout_seconds,
    get_streaming_tone_enabled,
    save,
    set_generate_presence_penalty,
    set_generate_top_k,
    set_generate_top_p,
    set_generate_temperature,
    set_gemini_config,
    set_image_format,
    set_image_max_side,
    set_image_quality,
    set_keep_alive,
    set_language,
    set_max_retries,
    set_num_ctx,
    set_progress_enabled,
    set_provider,
    set_ollama_config,
    set_request_metrics_log_path,
    set_request_metrics_logging_enabled,
    set_streaming_enabled,
    set_streaming_tone_enabled,
    set_timeout_seconds,
)
from ..providers.config import GeminiConfig, OllamaConfig

addonHandler.initTranslation()


class AIAssistantSettingsPanel(SettingsPanel):
    # TRANSLATORS: Title shown at the top of the AI Assistant settings panel.
    title = _("AI Assistant")

    def makeSettings(self, settingsSizer):
        sHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)

        provider = get_provider()
        ollama_config = get_ollama_config()
        gemini_config = get_gemini_config()
        # TRANSLATORS: Provider option label for Ollama.
        # TRANSLATORS: Provider option label for Gemini.
        self._providerOptions = [("ollama", _("Ollama")), ("gemini", _("Gemini"))]
        providerChoices = [label for _, label in self._providerOptions]
        selectedProviderIndex = next(
            (index for index, (value, _) in enumerate(self._providerOptions) if value == provider),
            0,
        )

        # TRANSLATORS: Section label for provider selection.
        providerGroupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Provider"))
        providerGroupHelper = sHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=providerGroupSizer))
        # TRANSLATORS: Label for the LLM provider dropdown.
        providerGroupHelper.addItem(wx.StaticText(self, label=_("LLM provider:")))
        self.providerChoice = wx.Choice(self, choices=providerChoices)
        self.providerChoice.SetSelection(selectedProviderIndex)
        self.providerChoice.Bind(wx.EVT_CHOICE, self._on_provider_choice)
        providerGroupHelper.addItem(self.providerChoice)

        self.ollamaGroupSizer = self._build_ollama_settings(sHelper, ollama_config)
        self.geminiGroupSizer = self._build_gemini_settings(sHelper, gemini_config)
        self.sharedGroupSizer = self._build_advanced_settings(sHelper)
        self.ollamaExpertGroupSizer = self._build_ollama_expert_settings(sHelper, ollama_config)
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

    def _build_ollama_settings(self, parentHelper, config: OllamaConfig):
        # TRANSLATORS: Section label for Ollama-specific settings.
        groupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Ollama Settings"))
        groupHelper = parentHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=groupSizer))
        # TRANSLATORS: Label for the Ollama model name setting.
        self.ollamaModelNameEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("Ollama model name:"),
            config.model_name or defaults.DEFAULT_OLLAMA_MODEL,
        )
        # TRANSLATORS: Label for the Ollama server URL setting.
        self.ollamaServerUrlEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("Ollama server URL:"),
            config.server_url or defaults.DEFAULT_OLLAMA_URL,
        )
        # TRANSLATORS: Label for the Ollama keep-alive duration setting.
        self.ollamaKeepAliveEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("Keep-alive duration:"),
            config.keep_alive or defaults.DEFAULT_KEEP_ALIVE,
        )
        # TRANSLATORS: Label for the Ollama context window size setting.
        self.ollamaNumCtxEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("Context window size (may affect performance):"),
            str(config.num_ctx if config.num_ctx is not None else defaults.DEFAULT_NUM_CTX),
        )
        return groupSizer

    def _build_gemini_settings(self, parentHelper, config: GeminiConfig):
        # TRANSLATORS: Section label for Gemini-specific settings.
        groupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Gemini Settings"))
        groupHelper = parentHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=groupSizer))
        # TRANSLATORS: Label for the Gemini model name setting.
        self.geminiModelNameEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("Gemini model name:"),
            config.model_name or defaults.DEFAULT_GEMINI_MODEL,
        )
        # TRANSLATORS: Label for the Gemini API key setting.
        self.geminiApiKeyEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("Gemini API key:"),
            config.api_key,
        )
        # TRANSLATORS: Label for the optional Gemini API token setting.
        self.geminiApiTokenEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("Gemini API token (optional):"),
            config.api_token or "",
        )
        # TRANSLATORS: Label for the Gemini base URL setting.
        self.geminiBaseUrlEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("Gemini base URL:"),
            config.base_url or defaults.DEFAULT_GEMINI_BASE_URL,
        )
        return groupSizer

    def _build_advanced_settings(self, parentHelper):
        # TRANSLATORS: Section label for shared runtime settings.
        groupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Shared Runtime Settings"))
        groupHelper = parentHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=groupSizer))
        # TRANSLATORS: Label for the request timeout setting.
        self.timeoutSecondsEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("Request timeout (seconds):"),
            str(get_timeout_seconds() if get_timeout_seconds() is not None else defaults.DEFAULT_TIMEOUT_SECONDS),
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
            str(get_image_max_side() if get_image_max_side() is not None else defaults.DEFAULT_IMAGE_MAX_SIDE),
        )
        self.imageFormatChoice = wx.Choice(self, choices=["PNG", "JPEG"])
        self.imageFormatChoice.SetSelection(
            ["PNG", "JPEG"].index(get_image_format())
            if get_image_format() in {"PNG", "JPEG"}
            else 0
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
        self.streamingCheckbox = groupHelper.addItem(
            wx.CheckBox(self, label=_("Enable streaming"))
        )
        # TRANSLATORS: Checkbox label for announcing progress.
        self.progressCheckbox = groupHelper.addItem(
            wx.CheckBox(self, label=_("Announce progress"))
        )
        # TRANSLATORS: Checkbox label for streaming tone feedback.
        self.streamingToneCheckbox = groupHelper.addItem(
            wx.CheckBox(self, label=_("Enable streaming tone feedback"))
        )
        self.streamingCheckbox.Value = get_streaming_enabled()
        self.progressCheckbox.Value = get_progress_enabled()
        self.streamingToneCheckbox.Value = get_streaming_tone_enabled()
        return groupSizer

    def _build_ollama_expert_settings(self, parentHelper, config: OllamaConfig):
        # TRANSLATORS: Section label for experimental Ollama expert settings.
        groupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Ollama Expert Settings (Experimental)"))
        groupHelper = parentHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=groupSizer))
        # TRANSLATORS: Label for the Ollama repetition penalty setting.
        self.presencePenaltyEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("Repetition penalty:"),
            str(get_generate_presence_penalty() if get_generate_presence_penalty() is not None else defaults.DEFAULT_GENERATE_PRESENCE_PENALTY),
        )
        # TRANSLATORS: Checkbox label for enabling Ollama think mode.
        self.ollamaThinkCheckbox = groupHelper.addItem(
            wx.CheckBox(self, label=_('Enable Ollama think mode'))
        )
        self.ollamaThinkCheckbox.Value = config.think
        return groupSizer

    def _build_expert_settings(self, parentHelper):
        # TRANSLATORS: Section label for general experimental settings.
        groupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Expert Settings (Experimental)"))
        groupHelper = parentHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=groupSizer))
        # TRANSLATORS: Label for the response creativity temperature setting.
        self.temperatureEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("Response creativity (temperature):"),
            str(get_generate_temperature() if get_generate_temperature() is not None else defaults.DEFAULT_GENERATE_TEMPERATURE),
        )
        # TRANSLATORS: Label for the Top-k sampling setting.
        self.topKEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("Top-k sampling:"),
            str(get_generate_top_k() if get_generate_top_k() is not None else defaults.DEFAULT_GENERATE_TOP_K),
        )
        # TRANSLATORS: Label for the Top-p sampling setting.
        self.topPEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("Top-p sampling:"),
            str(get_generate_top_p() if get_generate_top_p() is not None else defaults.DEFAULT_GENERATE_TOP_P),
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

    def onSave(self):
        ollamaModelName = self.ollamaModelNameEdit.Value.strip()
        ollamaServerUrl = self.ollamaServerUrlEdit.Value.strip()

        if self._selected_provider() == "ollama":
            if not ollamaModelName:
                # TRANSLATORS: Error shown when the Ollama model name field is empty.
                self._show_error(_("Ollama model name cannot be empty"))
                return

            if not ollamaServerUrl:
                # TRANSLATORS: Error shown when the Ollama server URL field is empty.
                self._show_error(_("Ollama server URL cannot be empty."))
                return

        timeoutSeconds = self._parse_float(
            self.timeoutSecondsEdit,
            # TRANSLATORS: Error shown when timeout is invalid.
            _("Timeout seconds must be a positive number."),
            minimum=0.000001,
        )
        if timeoutSeconds is None:
            return

        temperature = self._parse_float(
            self.temperatureEdit,
            # TRANSLATORS: Error shown when temperature is invalid.
            _("Generate temperature must be a non-negative number."),
            minimum=0.0,
        )
        if temperature is None:
            return

        topK = self._parse_int(
            self.topKEdit,
            # TRANSLATORS: Error shown when top-k value is invalid.
            _("Top-k sampling must be a non-negative integer."),
            minimum=0,
        )
        if topK is None:
            return

        topP = self._parse_float(
            self.topPEdit,
            # TRANSLATORS: Error shown when top-p value is invalid.
            _("Top-p sampling must be a non-negative number."),
            minimum=0.0,
        )
        if topP is None:
            return

        imageMaxSide = self._parse_int(
            self.imageMaxSideEdit,
            # TRANSLATORS: Error shown when image max side is invalid.
            _("Image max side length must be an integer of at least 128."),
            minimum=128,
        )
        if imageMaxSide is None:
            return

        imageFormatIndex = self.imageFormatChoice.GetSelection()
        if imageFormatIndex < 0 or imageFormatIndex >= 2:
            # TRANSLATORS: Error shown when an unsupported image format is selected.
            self._show_error(_("Image format must be PNG or JPEG."))
            return
        imageFormat = ["PNG", "JPEG"][imageFormatIndex]

        imageQuality = self._parse_int(
            self.imageQualityEdit,
            # TRANSLATORS: Error shown when image quality is invalid.
            _("Image quality must be an integer between 1 and 100."),
            minimum=1,
        )
        if imageQuality is None or imageQuality > 100:
            # TRANSLATORS: Error shown when image quality is outside the supported range.
            self._show_error(_("Image quality must be an integer between 1 and 100."))
            return

        requestMetricsLoggingEnabled = self.requestMetricsLoggingCheckbox.Value
        requestMetricsLogPath = self.requestMetricsLogPathEdit.Value.strip()
        if requestMetricsLoggingEnabled and not requestMetricsLogPath:
            # TRANSLATORS: Error shown when metrics logging is enabled but no path is entered.
            self._show_error(_("Metrics log file path cannot be empty when logging is enabled."))
            return

        provider = self._selected_provider()

        if provider == "ollama":
            ollamaKeepAlive = self.ollamaKeepAliveEdit.Value.strip()
            ollamaNumCtx = self._parse_int(
                self.ollamaNumCtxEdit,
                # TRANSLATORS: Error shown when Ollama context window size is invalid.
                _("Context window size must be an integer of at least 256."),
                minimum=256,
            )
            if ollamaNumCtx is None:
                return

            presencePenalty = self._parse_float(
                self.presencePenaltyEdit,
                # TRANSLATORS: Error shown when repetition penalty value is invalid.
                _("Repetition penalty must be a number."),
            )
            if presencePenalty is None:
                return

            config = OllamaConfig(
                provider="ollama",
                model_name=ollamaModelName,
                timeout_seconds=timeoutSeconds,
                enable_streaming=self.streamingCheckbox.Value,
                enable_progress=self.progressCheckbox.Value,
                num_ctx=ollamaNumCtx,
                max_retries=get_max_retries(),
                retry_backoff_seconds=get_retry_backoff_seconds(),
                generate_temperature=temperature,
                generate_top_k=topK,
                generate_top_p=topP,
                generate_presence_penalty=presencePenalty,
                server_url=ollamaServerUrl,
                keep_alive=ollamaKeepAlive,
                think=self.ollamaThinkCheckbox.Value,
            )
            set_ollama_config(config)
        else:
            geminiModelName = self.geminiModelNameEdit.Value.strip()
            geminiApiKey = self.geminiApiKeyEdit.Value.strip()
            geminiApiToken = self.geminiApiTokenEdit.Value.strip()
            geminiBaseUrl = self.geminiBaseUrlEdit.Value.strip()

            if not geminiModelName:
                # TRANSLATORS: Error shown when the Gemini model name field is empty.
                self._show_error(_("Gemini model name cannot be empty"))
                return
            if not geminiApiKey:
                # TRANSLATORS: Error shown when the Gemini API key field is empty.
                self._show_error(_("Gemini API key cannot be empty"))
                return
            if not geminiBaseUrl:
                # TRANSLATORS: Error shown when the Gemini base URL field is empty.
                self._show_error(_("Gemini base URL cannot be empty."))
                return

            current_config = get_gemini_config()
            config = GeminiConfig(
                provider="gemini",
                model_name=geminiModelName,
                timeout_seconds=timeoutSeconds,
                enable_streaming=self.streamingCheckbox.Value,
                enable_progress=self.progressCheckbox.Value,
                num_ctx=current_config.num_ctx,
                max_retries=get_max_retries(),
                retry_backoff_seconds=get_retry_backoff_seconds(),
                generate_temperature=temperature,
                generate_top_k=topK,
                generate_top_p=topP,
                api_key=geminiApiKey,
                api_token=geminiApiToken or None,
                base_url=geminiBaseUrl,
            )
            set_gemini_config(config)

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
        set_streaming_tone_enabled(self.streamingToneCheckbox.Value)

    def _selected_provider(self) -> str:
        index = self.providerChoice.GetSelection()
        if index < 0 or index >= len(self._providerOptions):
            return "ollama"
        return self._providerOptions[index][0]

    def _on_provider_choice(self, event: Any) -> None:
        self._update_provider_field_state()

    def _update_provider_field_state(self) -> None:
        provider = self._selected_provider()
        is_ollama = provider == "ollama"

        self.ollamaGroupSizer.ShowItems(is_ollama)
        self.geminiGroupSizer.ShowItems(not is_ollama)
        self.ollamaExpertGroupSizer.ShowItems(is_ollama)

        self.ollamaModelNameEdit.Enable(is_ollama)
        self.ollamaServerUrlEdit.Enable(is_ollama)
        self.geminiModelNameEdit.Enable(not is_ollama)
        self.geminiApiKeyEdit.Enable(not is_ollama)
        self.geminiApiTokenEdit.Enable(not is_ollama)
        self.geminiBaseUrlEdit.Enable(not is_ollama)
        self.presencePenaltyEdit.Enable(is_ollama)
        self.ollamaThinkCheckbox.Enable(is_ollama)

        self.Layout()
