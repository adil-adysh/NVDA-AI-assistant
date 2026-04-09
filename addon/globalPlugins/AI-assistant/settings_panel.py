# -*- coding: utf-8 -*-
import addonHandler
import wx

from gui import guiHelper
from gui.settingsDialogs import SettingsPanel

from . import defaults
from .settings import (
    get_generate_presence_penalty,
    get_generate_top_k,
    get_generate_top_p,
    get_generate_temperature,
    get_max_retries,
    get_model_name,
    get_num_ctx,
    get_progress_enabled,
    get_retry_backoff_seconds,
    get_server_url,
    get_streaming_enabled,
    get_timeout_seconds,
    save,
    set_generate_presence_penalty,
    set_generate_top_k,
    set_generate_top_p,
    set_generate_temperature,
    set_model_name,
    set_num_ctx,
    set_progress_enabled,
    set_server_url,
    set_streaming_enabled,
    set_timeout_seconds,
)

addonHandler.initTranslation()


class AIAssistantSettingsPanel(SettingsPanel):
    title = _("AI Assistant")

    def makeSettings(self, settingsSizer):
        sHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)

        basicGroupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Basic Settings"))
        basicGroupHelper = sHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=basicGroupSizer))
        self.modelNameEdit = self._add_labeled_text_ctrl(
            basicGroupHelper,
            _("Ollama model name:"),
            get_model_name() or defaults.DEFAULT_OLLAMA_MODEL,
        )
        self.serverUrlEdit = self._add_labeled_text_ctrl(
            basicGroupHelper,
            _("Ollama server URL:"),
            get_server_url() or defaults.DEFAULT_OLLAMA_URL,
        )
        self.streamingCheckbox = basicGroupHelper.addItem(
            wx.CheckBox(self, label=_("Enable streaming"))
        )
        self.progressCheckbox = basicGroupHelper.addItem(
            wx.CheckBox(self, label=_("Announce progress"))
        )
        self.streamingCheckbox.Value = get_streaming_enabled()
        self.progressCheckbox.Value = get_progress_enabled()

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
        modelName = self.modelNameEdit.Value.strip()
        serverUrl = self.serverUrlEdit.Value.strip()

        if not modelName:
            self._show_error(_("Model name cannot be empty"))
            return

        if not serverUrl:
            self._show_error(_("Server URL cannot be empty"))
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

        set_model_name(modelName)
        set_server_url(serverUrl)
        set_streaming_enabled(self.streamingCheckbox.Value)
        set_progress_enabled(self.progressCheckbox.Value)
        set_timeout_seconds(timeoutSeconds)
        set_num_ctx(numCtx)
        set_generate_temperature(temperature)
        set_generate_top_k(topK)
        set_generate_top_p(topP)
        set_generate_presence_penalty(presencePenalty)
        save()
