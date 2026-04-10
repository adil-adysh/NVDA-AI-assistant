# -*- coding: utf-8 -*-
import addonHandler
import wx
from typing import Any

from gui import guiHelper
from gui.settingsDialogs import SettingsPanel

from . import defaults
from .settings import (
    get_generate_presence_penalty,
    get_generate_top_k,
    get_generate_top_p,
    get_generate_temperature,
    get_gemini_config,
    get_keep_alive,
    get_max_retries,
    get_num_ctx,
    get_progress_enabled,
    get_provider,
    get_ollama_config,
    get_retry_backoff_seconds,
    get_streaming_enabled,
    get_timeout_seconds,
    save,
    set_generate_presence_penalty,
    set_generate_top_k,
    set_generate_top_p,
    set_generate_temperature,
    set_gemini_config,
    set_keep_alive,
    set_max_retries,
    set_num_ctx,
    set_progress_enabled,
    set_provider,
    set_ollama_config,
    set_streaming_enabled,
    set_timeout_seconds,
)
from .providers.config import GeminiConfig, OllamaConfig

addonHandler.initTranslation()


class AIAssistantSettingsPanel(SettingsPanel):
    title = _("AI Assistant")

    def makeSettings(self, settingsSizer):
        sHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)

        provider = get_provider()
        ollama_config = get_ollama_config()
        gemini_config = get_gemini_config()
        self._providerOptions = [("ollama", _("Ollama")), ("gemini", _("Gemini"))]
        providerChoices = [label for _, label in self._providerOptions]
        selectedProviderIndex = next(
            (index for index, (value, _) in enumerate(self._providerOptions) if value == provider),
            0,
        )

        providerGroupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Provider"))
        providerGroupHelper = sHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=providerGroupSizer))
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

    def _build_ollama_settings(self, parentHelper, config: OllamaConfig):
        groupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Ollama Settings"))
        groupHelper = parentHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=groupSizer))
        self.ollamaModelNameEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("Ollama model name:"),
            config.model_name or defaults.DEFAULT_OLLAMA_MODEL,
        )
        self.ollamaServerUrlEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("Ollama server URL:"),
            config.server_url or defaults.DEFAULT_OLLAMA_URL,
        )
        self.ollamaKeepAliveEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("Keep-alive duration:"),
            config.keep_alive or defaults.DEFAULT_KEEP_ALIVE,
        )
        self.ollamaNumCtxEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("Context window size (may affect performance):"),
            str(config.num_ctx if config.num_ctx is not None else defaults.DEFAULT_NUM_CTX),
        )
        return groupSizer

    def _build_gemini_settings(self, parentHelper, config: GeminiConfig):
        groupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Gemini Settings"))
        groupHelper = parentHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=groupSizer))
        self.geminiModelNameEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("Gemini model name:"),
            config.model_name or defaults.DEFAULT_GEMINI_MODEL,
        )
        self.geminiApiKeyEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("Gemini API key:"),
            config.api_key,
        )
        self.geminiApiTokenEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("Gemini API token (optional):"),
            config.api_token or "",
        )
        self.geminiBaseUrlEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("Gemini base URL:"),
            config.base_url or defaults.DEFAULT_GEMINI_BASE_URL,
        )
        return groupSizer

    def _build_advanced_settings(self, parentHelper):
        groupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Shared Runtime Settings"))
        groupHelper = parentHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=groupSizer))
        self.timeoutSecondsEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("Request timeout (seconds):"),
            str(get_timeout_seconds() if get_timeout_seconds() is not None else defaults.DEFAULT_TIMEOUT_SECONDS),
        )
        self.streamingCheckbox = groupHelper.addItem(
            wx.CheckBox(self, label=_("Enable streaming"))
        )
        self.progressCheckbox = groupHelper.addItem(
            wx.CheckBox(self, label=_("Announce progress"))
        )
        self.streamingCheckbox.Value = get_streaming_enabled()
        self.progressCheckbox.Value = get_progress_enabled()
        return groupSizer

    def _build_ollama_expert_settings(self, parentHelper, config: OllamaConfig):
        groupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Ollama Expert Settings (Experimental)"))
        groupHelper = parentHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=groupSizer))
        self.presencePenaltyEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("Repetition penalty:"),
            str(get_generate_presence_penalty() if get_generate_presence_penalty() is not None else defaults.DEFAULT_GENERATE_PRESENCE_PENALTY),
        )
        return groupSizer

    def _build_expert_settings(self, parentHelper):
        groupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Expert Settings (Experimental)"))
        groupHelper = parentHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=groupSizer))
        self.temperatureEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("Response creativity (temperature):"),
            str(get_generate_temperature() if get_generate_temperature() is not None else defaults.DEFAULT_GENERATE_TEMPERATURE),
        )
        self.topKEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("Top-k sampling:"),
            str(get_generate_top_k() if get_generate_top_k() is not None else defaults.DEFAULT_GENERATE_TOP_K),
        )
        self.topPEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("Top-p sampling:"),
            str(get_generate_top_p() if get_generate_top_p() is not None else defaults.DEFAULT_GENERATE_TOP_P),
        )
        self.presencePenaltyEdit = self._add_labeled_text_ctrl(
            groupHelper,
            _("Repetition penalty:"),
            str(get_generate_presence_penalty() if get_generate_presence_penalty() is not None else defaults.DEFAULT_GENERATE_PRESENCE_PENALTY),
        )
        return groupSizer

    def _show_error(self, message: str) -> None:
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
                self._show_error(_("Ollama model name cannot be empty"))
                return

            if not ollamaServerUrl:
                self._show_error(_("Ollama server URL cannot be empty."))
                return

        timeoutSeconds = self._parse_float(
            self.timeoutSecondsEdit,
            _("Timeout seconds must be a positive number."),
            minimum=0.000001,
        )
        if timeoutSeconds is None:
            return

        numCtx = self._parse_int(
            self.numCtxEdit,
            _("num_ctx must be an integer of at least 256."),
            minimum=256,
        )
        if numCtx is None:
            return

        keepAlive = self.keepAliveEdit.Value.strip()
        if not keepAlive:
            self._show_error(_("Keep-alive duration cannot be empty."))
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

        provider = self._selected_provider()

        if provider == "ollama":
            ollamaKeepAlive = self.ollamaKeepAliveEdit.Value.strip()
            ollamaNumCtx = self._parse_int(
                self.ollamaNumCtxEdit,
                _("Context window size must be an integer of at least 256."),
                minimum=256,
            )
            if ollamaNumCtx is None:
                return

            presencePenalty = self._parse_float(
                self.presencePenaltyEdit,
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
            )
            set_ollama_config(config)
        else:
            geminiModelName = self.geminiModelNameEdit.Value.strip()
            geminiApiKey = self.geminiApiKeyEdit.Value.strip()
            geminiApiToken = self.geminiApiTokenEdit.Value.strip()
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
                generate_presence_penalty=presencePenalty,
                api_key=geminiApiKey,
                api_token=geminiApiToken or None,
                base_url=geminiBaseUrl,
            )
            set_gemini_config(config)

        save()

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

        self.Layout()
