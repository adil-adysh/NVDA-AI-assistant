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

        modelGroupText = _("Ollama model settings")
        modelGroupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=modelGroupText)
        modelGroupHelper = sHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=modelGroupSizer))

        modelNameLabel = wx.StaticText(self, label=_("Ollama model name:"))
        self.modelNameEdit = wx.TextCtrl(self)
        modelGroupHelper.addItem(modelNameLabel)
        modelGroupHelper.addItem(self.modelNameEdit)

        serverUrlLabel = wx.StaticText(self, label=_("Ollama server URL:"))
        self.serverUrlEdit = wx.TextCtrl(self)
        modelGroupHelper.addItem(serverUrlLabel)
        modelGroupHelper.addItem(self.serverUrlEdit)

        behaviorGroupText = _("Behavior settings")
        behaviorGroupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=behaviorGroupText)
        behaviorGroupHelper = sHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=behaviorGroupSizer))

        self.streamingCheckbox = behaviorGroupHelper.addItem(
            wx.CheckBox(self, label=_("Enable streaming"))
        )

        self.progressCheckbox = behaviorGroupHelper.addItem(
            wx.CheckBox(self, label=_("Announce progress"))
        )

        advancedGroupText = _("Advanced Ollama options")
        advancedGroupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=advancedGroupText)
        advancedGroupHelper = sHelper.addItem(guiHelper.BoxSizerHelper(self, sizer=advancedGroupSizer))

        timeoutLabel = wx.StaticText(self, label=_("Request timeout seconds:"))
        self.timeoutSecondsEdit = wx.TextCtrl(self)
        advancedGroupHelper.addItem(timeoutLabel)
        advancedGroupHelper.addItem(self.timeoutSecondsEdit)

        numCtxLabel = wx.StaticText(self, label=_("Ollama context window size (num_ctx):"))
        self.numCtxEdit = wx.TextCtrl(self)
        advancedGroupHelper.addItem(numCtxLabel)
        advancedGroupHelper.addItem(self.numCtxEdit)

        keepAliveLabel = wx.StaticText(self, label=_("Ollama keep_alive:"))
        self.keepAliveEdit = wx.TextCtrl(self)
        advancedGroupHelper.addItem(keepAliveLabel)
        advancedGroupHelper.addItem(self.keepAliveEdit)

        maxRetriesLabel = wx.StaticText(self, label=_("Ollama max retries:"))
        self.maxRetriesEdit = wx.TextCtrl(self)
        advancedGroupHelper.addItem(maxRetriesLabel)
        advancedGroupHelper.addItem(self.maxRetriesEdit)

        retryBackoffLabel = wx.StaticText(self, label=_("Retry backoff seconds:"))
        self.retryBackoffSecondsEdit = wx.TextCtrl(self)
        advancedGroupHelper.addItem(retryBackoffLabel)
        advancedGroupHelper.addItem(self.retryBackoffSecondsEdit)

        temperatureLabel = wx.StaticText(self, label=_("Generate temperature:"))
        self.temperatureEdit = wx.TextCtrl(self)
        advancedGroupHelper.addItem(temperatureLabel)
        advancedGroupHelper.addItem(self.temperatureEdit)

        topKLabel = wx.StaticText(self, label=_("Generate top_k:"))
        self.topKEdit = wx.TextCtrl(self)
        advancedGroupHelper.addItem(topKLabel)
        advancedGroupHelper.addItem(self.topKEdit)

        topPLabel = wx.StaticText(self, label=_("Generate top_p:"))
        self.topPEdit = wx.TextCtrl(self)
        advancedGroupHelper.addItem(topPLabel)
        advancedGroupHelper.addItem(self.topPEdit)

        presencePenaltyLabel = wx.StaticText(self, label=_("Generate presence_penalty:"))
        self.presencePenaltyEdit = wx.TextCtrl(self)
        advancedGroupHelper.addItem(presencePenaltyLabel)
        advancedGroupHelper.addItem(self.presencePenaltyEdit)

        self.modelNameEdit.Value = get_model_name()
        self.serverUrlEdit.Value = get_server_url()
        self.streamingCheckbox.Value = is_streaming_enabled()
        self.progressCheckbox.Value = is_progress_enabled()
        self.timeoutSecondsEdit.Value = str(get_timeout_seconds())
        self.numCtxEdit.Value = str(get_num_ctx())
        self.keepAliveEdit.Value = get_keep_alive()
        self.maxRetriesEdit.Value = str(get_max_retries())
        self.retryBackoffSecondsEdit.Value = str(get_retry_backoff_seconds())
        self.temperatureEdit.Value = str(get_generate_temperature())
        self.topKEdit.Value = str(get_generate_top_k())
        self.topPEdit.Value = str(get_generate_top_p())
        self.presencePenaltyEdit.Value = str(get_generate_presence_penalty())

    def onSave(self):
        modelName = self.modelNameEdit.Value.strip()
        serverUrl = self.serverUrlEdit.Value.strip()

        if not modelName:
            wx.MessageBox(
                _("Model name cannot be empty"),
                _("Error"),
                wx.ICON_ERROR,
            )
            return

        if not serverUrl:
            wx.MessageBox(
                _("Server URL cannot be empty"),
                _("Error"),
                wx.ICON_ERROR,
            )
            return

        try:
            timeoutSeconds = float(self.timeoutSecondsEdit.Value.strip())
            if timeoutSeconds <= 0:
                raise ValueError
        except ValueError:
            wx.MessageBox(
                _("Timeout seconds must be a positive number."),
                _("Error"),
                wx.ICON_ERROR,
            )
            return

        try:
            numCtx = int(self.numCtxEdit.Value.strip())
            if numCtx < 256:
                raise ValueError
        except ValueError:
            wx.MessageBox(
                _("num_ctx must be an integer of at least 256."),
                _("Error"),
                wx.ICON_ERROR,
            )
            return

        keepAlive = self.keepAliveEdit.Value.strip()
        if not keepAlive:
            wx.MessageBox(
                _("Keep-alive cannot be empty."),
                _("Error"),
                wx.ICON_ERROR,
            )
            return

        try:
            maxRetries = int(self.maxRetriesEdit.Value.strip())
            if maxRetries < 0:
                raise ValueError
        except ValueError:
            wx.MessageBox(
                _("Max retries must be a non-negative integer."),
                _("Error"),
                wx.ICON_ERROR,
            )
            return

        try:
            retryBackoffSeconds = float(self.retryBackoffSecondsEdit.Value.strip())
            if retryBackoffSeconds < 0:
                raise ValueError
        except ValueError:
            wx.MessageBox(
                _("Retry backoff seconds must be a non-negative number."),
                _("Error"),
                wx.ICON_ERROR,
            )
            return

        try:
            temperature = float(self.temperatureEdit.Value.strip())
            if temperature < 0:
                raise ValueError
        except ValueError:
            wx.MessageBox(
                _("Generate temperature must be a non-negative number."),
                _("Error"),
                wx.ICON_ERROR,
            )
            return

        try:
            topK = int(self.topKEdit.Value.strip())
            if topK < 0:
                raise ValueError
        except ValueError:
            wx.MessageBox(
                _("Generate top_k must be a non-negative integer."),
                _("Error"),
                wx.ICON_ERROR,
            )
            return

        try:
            topP = float(self.topPEdit.Value.strip())
            if topP < 0:
                raise ValueError
        except ValueError:
            wx.MessageBox(
                _("Generate top_p must be a non-negative number."),
                _("Error"),
                wx.ICON_ERROR,
            )
            return

        try:
            presencePenalty = float(self.presencePenaltyEdit.Value.strip())
        except ValueError:
            wx.MessageBox(
                _("Generate presence_penalty must be a number."),
                _("Error"),
                wx.ICON_ERROR,
            )
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
