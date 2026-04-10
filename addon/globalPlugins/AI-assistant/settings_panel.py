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
    get_gemini_api_key,
    get_gemini_api_token,
    get_gemini_base_url,
    get_gemini_model_name,
    get_keep_alive,
    get_max_retries,
    get_num_ctx,
    get_progress_enabled,
    get_provider,
    get_ollama_model_name,
    get_ollama_server_url,
    get_retry_backoff_seconds,
    get_streaming_enabled,
    get_timeout_seconds,
    save,
    set_generate_presence_penalty,
    set_generate_top_k,
    set_generate_top_p,
    set_generate_temperature,
    set_gemini_api_key,
    set_gemini_api_token,
    set_gemini_base_url,
    set_gemini_model_name,
    set_keep_alive,
    set_max_retries,
    set_num_ctx,
    set_progress_enabled,
    set_provider,
    set_ollama_model_name,
    set_ollama_server_url,
    set_gemini_base_url,
    set_streaming_enabled,
    set_timeout_seconds,
)

addonHandler.initTranslation()


class AIAssistantSettingsPanel(SettingsPanel):
    title = _("AI Assistant")

    def makeSettings(self, settingsSizer):
        sHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)

        provider = get_provider()
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

        basicGroupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Ollama Settings"))
        basicGroupHelper = sHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=basicGroupSizer))
        self.ollamaModelNameEdit = self._add_labeled_text_ctrl(
            basicGroupHelper,
            _("Ollama model name:"),
            get_ollama_model_name() or defaults.DEFAULT_OLLAMA_MODEL,
        )
        self.ollamaServerUrlEdit = self._add_labeled_text_ctrl(
            basicGroupHelper,
            _("Ollama server URL:"),
            get_ollama_server_url() or defaults.DEFAULT_OLLAMA_URL,
        )
        self.streamingCheckbox = basicGroupHelper.addItem(
            wx.CheckBox(self, label=_("Enable streaming"))
        )
        self.progressCheckbox = basicGroupHelper.addItem(
            wx.CheckBox(self, label=_("Announce progress"))
        )
        self.streamingCheckbox.Value = get_streaming_enabled()
        self.progressCheckbox.Value = get_progress_enabled()

        geminiGroupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Gemini Settings"))
        geminiGroupHelper = sHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=geminiGroupSizer))
        self.geminiModelNameEdit = self._add_labeled_text_ctrl(
            geminiGroupHelper,
            _("Gemini model name:"),
            get_gemini_model_name() or defaults.DEFAULT_GEMINI_MODEL,
        )
        self.geminiApiKeyEdit = self._add_labeled_text_ctrl(
            geminiGroupHelper,
            _("Gemini API key:"),
            get_gemini_api_key(),
        )
        self.geminiApiTokenEdit = self._add_labeled_text_ctrl(
            geminiGroupHelper,
            _("Gemini API token (optional):"),
            get_gemini_api_token(),
        )
        self.geminiBaseUrlEdit = self._add_labeled_text_ctrl(
            geminiGroupHelper,
            _("Gemini base URL:"),
            get_gemini_base_url() or defaults.DEFAULT_GEMINI_BASE_URL,
        )

        self._update_provider_field_state()

        advancedGroupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Advanced Settings"))
        advancedGroupHelper = sHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=advancedGroupSizer))
        self.timeoutSecondsEdit = self._add_labeled_text_ctrl(
            advancedGroupHelper,
            _("Request timeout (seconds):"),
            str(get_timeout_seconds() if get_timeout_seconds() is not None else defaults.DEFAULT_TIMEOUT_SECONDS),
        )
        self.numCtxEdit = self._add_labeled_text_ctrl(
            advancedGroupHelper,
            _("Context window size (may affect performance):"),
            str(get_num_ctx() if get_num_ctx() is not None else defaults.DEFAULT_NUM_CTX),
        )
        self.keepAliveEdit = self._add_labeled_text_ctrl(
            advancedGroupHelper,
            _("Keep-alive duration:"),
            get_keep_alive() or defaults.DEFAULT_KEEP_ALIVE,
        )

        expertGroupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Expert Settings (Experimental)"))
        expertGroupHelper = sHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=expertGroupSizer))
        self.temperatureEdit = self._add_labeled_text_ctrl(
            expertGroupHelper,
            _("Response creativity (temperature):"),
            str(get_generate_temperature() if get_generate_temperature() is not None else defaults.DEFAULT_GENERATE_TEMPERATURE),
        )
        self.topKEdit = self._add_labeled_text_ctrl(
            expertGroupHelper,
            _("Top-k sampling:"),
            str(get_generate_top_k() if get_generate_top_k() is not None else defaults.DEFAULT_GENERATE_TOP_K),
        )
        self.topPEdit = self._add_labeled_text_ctrl(
            expertGroupHelper,
            _("Top-p sampling:"),
            str(get_generate_top_p() if get_generate_top_p() is not None else defaults.DEFAULT_GENERATE_TOP_P),
        )
        self.presencePenaltyEdit = self._add_labeled_text_ctrl(
            expertGroupHelper,
            _("Repetition penalty:"),
            str(get_generate_presence_penalty() if get_generate_presence_penalty() is not None else defaults.DEFAULT_GENERATE_PRESENCE_PENALTY),
        )

    def _add_labeled_text_ctrl(self, helper, label, initialValue):
        labelControl = wx.StaticText(self, label=label)
        textControl = wx.TextCtrl(self)
        textControl.Value = str(initialValue)
        helper.addItem(labelControl)
        helper.addItem(textControl)
        return textControl

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

        presencePenalty = self._parse_float(
            self.presencePenaltyEdit,
            _("Repetition penalty must be a number."),
        )
        if presencePenalty is None:
            return

        provider = self._selected_provider()

        if provider == "ollama":
            set_ollama_model_name(ollamaModelName)
            set_ollama_server_url(ollamaServerUrl)
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

            set_gemini_model_name(geminiModelName)
            set_gemini_api_key(geminiApiKey)
            set_gemini_api_token(geminiApiToken)
            set_gemini_base_url(geminiBaseUrl)

        set_provider(provider)
        set_streaming_enabled(self.streamingCheckbox.Value)
        set_progress_enabled(self.progressCheckbox.Value)
        set_timeout_seconds(timeoutSeconds)
        set_num_ctx(numCtx)
        set_keep_alive(keepAlive)
        set_generate_temperature(temperature)
        set_generate_top_k(topK)
        set_generate_top_p(topP)
        set_generate_presence_penalty(presencePenalty)
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

        self.ollamaModelNameEdit.Enable(is_ollama)
        self.ollamaServerUrlEdit.Enable(is_ollama)
        self.geminiModelNameEdit.Enable(not is_ollama)
        self.geminiApiKeyEdit.Enable(not is_ollama)
        self.geminiApiTokenEdit.Enable(not is_ollama)
        self.geminiBaseUrlEdit.Enable(not is_ollama)
