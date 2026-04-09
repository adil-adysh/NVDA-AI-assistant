# -*- coding: utf-8 -*-
import wx

from gui import guiHelper
from gui.settingsDialogs import SettingsPanel

from .settings import (
    get_generate_presence_penalty,
    get_generate_top_k,
    get_generate_top_p,
    get_generate_temperature,
    get_keep_alive,
    get_max_retries,
    get_model_name,
    get_num_ctx,
    get_retry_backoff_seconds,
    get_server_url,
    get_timeout_seconds,
    get_progress_enabled,
    get_streaming_enabled,
    save,
    set_generate_presence_penalty,
    set_generate_top_k,
    set_generate_top_p,
    set_generate_temperature,
    set_keep_alive,
    set_max_retries,
    set_model_name,
    set_num_ctx,
    set_progress_enabled,
    set_retry_backoff_seconds,
    set_server_url,
    set_streaming_enabled,
    set_timeout_seconds,
)


class AIAssistantSettingsPanel(SettingsPanel):
    title = _("AI Assistant")

    def makeSettings(self, settingsSizer):
        sHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)

        modelGroupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Ollama model settings"))
        modelGroupHelper = sHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=modelGroupSizer))
        self.modelNameEdit = self._add_labeled_text_ctrl(
            modelGroupHelper,
            _("Ollama model name:"),
            get_model_name(),
        )
        self.serverUrlEdit = self._add_labeled_text_ctrl(
            modelGroupHelper,
            _("Ollama server URL:"),
            get_server_url(),
        )

        behaviorGroupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Behavior settings"))
        behaviorGroupHelper = sHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=behaviorGroupSizer))
        self.streamingCheckbox = behaviorGroupHelper.addItem(
            wx.CheckBox(self, label=_("Enable streaming"))
        )
        self.progressCheckbox = behaviorGroupHelper.addItem(
            wx.CheckBox(self, label=_("Announce progress"))
        )
        self.streamingCheckbox.Value = get_streaming_enabled()
        self.progressCheckbox.Value = get_progress_enabled()

        advancedGroupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Advanced Ollama options"))
        advancedGroupHelper = sHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=advancedGroupSizer))
        self.timeoutSecondsEdit = self._add_labeled_text_ctrl(
            advancedGroupHelper,
            _("Request timeout seconds:"),
            str(get_timeout_seconds()),
        )
        self.numCtxEdit = self._add_labeled_text_ctrl(
            advancedGroupHelper,
            _("Ollama context window size (num_ctx):"),
            str(get_num_ctx()),
        )
        self.keepAliveEdit = self._add_labeled_text_ctrl(
            advancedGroupHelper,
            _("Ollama keep_alive:"),
            get_keep_alive(),
        )
        self.maxRetriesEdit = self._add_labeled_text_ctrl(
            advancedGroupHelper,
            _("Ollama max retries:"),
            str(get_max_retries()),
        )
        self.retryBackoffSecondsEdit = self._add_labeled_text_ctrl(
            advancedGroupHelper,
            _("Retry backoff seconds:"),
            str(get_retry_backoff_seconds()),
        )
        self.temperatureEdit = self._add_labeled_text_ctrl(
            advancedGroupHelper,
            _("Generate temperature:"),
            str(get_generate_temperature()),
        )
        self.topKEdit = self._add_labeled_text_ctrl(
            advancedGroupHelper,
            _("Generate top_k:"),
            str(get_generate_top_k()),
        )
        self.topPEdit = self._add_labeled_text_ctrl(
            advancedGroupHelper,
            _("Generate top_p:"),
            str(get_generate_top_p()),
        )
        self.presencePenaltyEdit = self._add_labeled_text_ctrl(
            advancedGroupHelper,
            _("Generate presence_penalty:"),
            str(get_generate_presence_penalty()),
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

        keepAlive = self.keepAliveEdit.Value.strip()
        if not keepAlive:
            self._show_error(_("Keep-alive cannot be empty."))
            return

        maxRetries = self._parse_int(
            self.maxRetriesEdit,
            _("Max retries must be a non-negative integer."),
            minimum=0,
        )
        if maxRetries is None:
            return

        retryBackoffSeconds = self._parse_float(
            self.retryBackoffSecondsEdit,
            _("Retry backoff seconds must be a non-negative number."),
            minimum=0.0,
        )
        if retryBackoffSeconds is None:
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
            _("Generate top_k must be a non-negative integer."),
            minimum=0,
        )
        if topK is None:
            return

        topP = self._parse_float(
            self.topPEdit,
            _("Generate top_p must be a non-negative number."),
            minimum=0.0,
        )
        if topP is None:
            return

        presencePenalty = self._parse_float(
            self.presencePenaltyEdit,
            _("Generate presence_penalty must be a number."),
        )
        if presencePenalty is None:
            return

        set_model_name(modelName)
        set_server_url(serverUrl)
        set_streaming_enabled(self.streamingCheckbox.Value)
        set_progress_enabled(self.progressCheckbox.Value)
        set_timeout_seconds(timeoutSeconds)
        set_num_ctx(numCtx)
        set_keep_alive(keepAlive)
        set_max_retries(maxRetries)
        set_retry_backoff_seconds(retryBackoffSeconds)
        set_generate_temperature(temperature)
        set_generate_top_k(topK)
        set_generate_top_p(topP)
        set_generate_presence_penalty(presencePenalty)
        save()
