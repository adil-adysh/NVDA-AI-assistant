# -*- coding: utf-8 -*-
import addonHandler
import wx
from pathlib import Path
from typing import Any

from gui import guiHelper
from gui.settingsDialogs import SettingsPanel

from ..config import defaults
from ..config.settings import (
    get_generate_max_tokens,
    get_generate_presence_penalty,
    get_generate_top_k,
    get_generate_top_p,
    get_generate_temperature,
    get_image_format,
    get_image_quality,
    get_image_max_side,
    get_language,
    get_max_retries,
    get_num_ctx,
    get_openai_compat_config,
    get_progress_enabled,
    get_provider,
    get_request_metrics_log_path,
    get_request_metrics_logging_enabled,
    get_retry_backoff_seconds,
    get_streaming_enabled,
    get_timeout_seconds,
    get_streaming_tone_enabled,
    set_image_format,
    set_image_max_side,
    set_image_quality,
    set_language,
    set_num_ctx,
    set_openai_compat_config,
    set_request_metrics_log_path,
    set_request_metrics_logging_enabled,
    set_streaming_enabled,
    set_streaming_tone_enabled,
)
from ..providers.config import OpenAICompatConfig

addonHandler.initTranslation()


class AIAssistantSettingsPanel(SettingsPanel):
    # TRANSLATORS: Title shown at the top of the AI Assistant settings panel.
    title = _("AI Assistant")

    def makeSettings(self, settingsSizer):
        sHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)

        provider = get_provider()
        config = get_openai_compat_config()
        # TRANSLATORS: Provider option label for Ollama.
        # TRANSLATORS: Provider option label for Gemini.
        self._providerOptions = [("ollama", _("Ollama")), ("gemini", _("Gemini")), ("openai", _("OpenAI")), ("litert-lm", _("LiteRT-LM"))]
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

        self.ollamaGroupSizer = self._build_ollama_settings(sHelper, config)
        self.geminiGroupSizer = self._build_gemini_settings(sHelper, config)
        self.openaiGroupSizer = self._build_openai_settings(sHelper, config)
        self.litertGroupSizer = self._build_litert_settings(sHelper)
        self.sharedGroupSizer = self._build_advanced_settings(sHelper)
        self.ollamaExpertGroupSizer = self._build_ollama_expert_settings(sHelper, config)
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

    def _build_ollama_settings(self, parentHelper, config: OpenAICompatConfig):
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
            config.base_url or defaults.DEFAULT_OLLAMA_URL,
        )
        # TRANSLATORS: Label for the Ollama context window size setting.
        self.ollamaNumCtxEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("Context window size (may affect performance):"),
            str(config.num_ctx if config.num_ctx is not None else defaults.DEFAULT_NUM_CTX),
        )
        return groupSizer

    def _build_gemini_settings(self, parentHelper, config: OpenAICompatConfig):
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
        # TRANSLATORS: Label for the Gemini base URL setting.
        self.geminiBaseUrlEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("Gemini base URL:"),
            config.base_url or defaults.DEFAULT_GEMINI_BASE_URL,
        )
        return groupSizer

    def _build_openai_settings(self, parentHelper, config: OpenAICompatConfig):
        groupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("OpenAI Settings"))
        groupHelper = parentHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=groupSizer))
        self.openaiModelNameEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("OpenAI model name:"),
            config.model_name or defaults.DEFAULT_OPENAI_MODEL,
        )
        self.openaiApiKeyEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("OpenAI API key:"),
            config.api_key or "",
        )
        self.openaiBaseUrlEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("OpenAI base URL:"),
            config.base_url or defaults.DEFAULT_OPENAI_BASE_URL,
        )
        return groupSizer

    def _build_litert_settings(self, parentHelper):
        # TRANSLATORS: Section label for LiteRT-LM-specific settings.
        groupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("LiteRT-LM Settings"))
        groupHelper = parentHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=groupSizer))
        litert_config = get_openai_compat_config()
        # TRANSLATORS: Label for the LiteRT-LM model name setting.
        self.litertModelNameEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("LiteRT-LM model name:"),
            litert_config.model_name or defaults.DEFAULT_LITERT_MODEL,
        )
        # TRANSLATORS: Label for the LiteRT-LM server URL setting.
        self.litertServerUrlEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("LiteRT-LM server URL:"),
            litert_config.base_url or defaults.DEFAULT_LITERT_URL,
        )
        # TRANSLATORS: Label for the LiteRT-LM context window size setting.
        self.litertNumCtxEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("LiteRT-LM context window size (may affect performance):"),
            str(get_num_ctx()),
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

    def _build_ollama_expert_settings(self, parentHelper, config: OpenAICompatConfig):
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
        provider = self._selected_provider()

        # Common field validation based on provider.
        if provider == "ollama":
            ollamaModelName = self.ollamaModelNameEdit.Value.strip()
            ollamaServerUrl = self.ollamaServerUrlEdit.Value.strip()
            if not ollamaModelName:
                self._show_error(_("Ollama model name cannot be empty"))
                return
            if not ollamaServerUrl:
                self._show_error(_("Ollama server URL cannot be empty."))
                return
        elif provider == "gemini":
            geminiModelName = self.geminiModelNameEdit.Value.strip()
            geminiApiKey = self.geminiApiKeyEdit.Value.strip()
            geminiBaseUrl = self.geminiBaseUrlEdit.Value.strip()
            if not geminiModelName:
                self._show_error(_("Gemini model name cannot be empty"))
                return
            if not geminiApiKey:
                self._show_error(_("Gemini API key cannot be empty"))
                return
            if not geminiBaseUrl:
                self._show_error(_("Gemini base URL cannot be empty."))
                return
        elif provider == "openai":
            openaiModelName = self.openaiModelNameEdit.Value.strip()
            openaiApiKey = self.openaiApiKeyEdit.Value.strip()
            openaiBaseUrl = self.openaiBaseUrlEdit.Value.strip()
            if not openaiModelName:
                self._show_error(_("OpenAI model name cannot be empty"))
                return
            if not openaiApiKey:
                self._show_error(_("OpenAI API key cannot be empty"))
                return
            if not openaiBaseUrl:
                self._show_error(_("OpenAI base URL cannot be empty."))
                return
        elif provider == "litert-lm":
            litertModelName = self.litertModelNameEdit.Value.strip()
            if not litertModelName:
                self._show_error(_("LiteRT-LM model name cannot be empty"))
                return
            litertNumCtx = self._parse_int(
                self.litertNumCtxEdit,
                _("Context window size must be an integer of at least 256."),
                minimum=256,
            )
            if litertNumCtx is None:
                return
            set_num_ctx(litertNumCtx)

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

        # Build unified config based on provider.
        model_name = ""
        base_url = ""
        api_key = ""

        if provider == "ollama":
            model_name = self.ollamaModelNameEdit.Value.strip()
            base_url = self.ollamaServerUrlEdit.Value.strip()
            ollamaNumCtx = self._parse_int(
                self.ollamaNumCtxEdit,
                _("Context window size must be an integer of at least 256."),
                minimum=256,
            )
            if ollamaNumCtx is None:
                return
            num_ctx = ollamaNumCtx
        elif provider == "gemini":
            model_name = self.geminiModelNameEdit.Value.strip()
            base_url = self.geminiBaseUrlEdit.Value.strip()
            api_key = self.geminiApiKeyEdit.Value.strip()
            num_ctx = get_num_ctx()
        elif provider == "openai":
            model_name = self.openaiModelNameEdit.Value.strip()
            base_url = self.openaiBaseUrlEdit.Value.strip()
            api_key = self.openaiApiKeyEdit.Value.strip()
            num_ctx = get_num_ctx()
        else:  # litert-lm
            model_name = self.litertModelNameEdit.Value.strip()
            base_url = self.litertServerUrlEdit.Value.strip()
            num_ctx = get_num_ctx()

        if provider == "ollama":
            think_widget = getattr(self, "ollamaThinkCheckbox", None)
            think_value = think_widget.Value if think_widget is not None else False
        else:
            think_value = get_openai_compat_config().think

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
        if index < 0 or index >= len(self._providerOptions):
            return "ollama"
        return self._providerOptions[index][0]

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
        self.geminiModelNameEdit.Enable(is_gemini)
        self.geminiApiKeyEdit.Enable(is_gemini)
        self.geminiApiTokenEdit.Enable(is_gemini)
        self.geminiBaseUrlEdit.Enable(is_gemini)
        self.openaiModelNameEdit.Enable(is_openai)
        self.openaiApiKeyEdit.Enable(is_openai)
        self.openaiBaseUrlEdit.Enable(is_openai)
        self.openaiChatPathEdit.Enable(is_openai)
        self.openaiMaxTokensEdit.Enable(is_openai)
        self.litertModelNameEdit.Enable(is_litert)
        self.litertServerUrlEdit.Enable(is_litert)
        self.litertNumCtxEdit.Enable(is_litert)
        self.presencePenaltyEdit.Enable(is_ollama)
        self.ollamaThinkCheckbox.Enable(is_ollama)

        self.Layout()
