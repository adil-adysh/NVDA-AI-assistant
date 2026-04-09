# -*- coding: utf-8 -*-
import wx

from gui import guiHelper
from gui.settingsDialogs import SettingsPanel

from .settings import (
    get_model_name,
    get_server_url,
    is_progress_enabled,
    is_streaming_enabled,
    save,
    set_model_name,
    set_progress_enabled,
    set_server_url,
    set_streaming_enabled,
)


class AIAssistantSettingsPanel(SettingsPanel):
    title = _("AI Assistant")

    def makeSettings(self, settingsSizer):
        sHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)

        self.modelNameEdit = sHelper.addItem(wx.TextCtrl(self))
        self.serverUrlEdit = sHelper.addItem(wx.TextCtrl(self))

        self.streamingCheckbox = sHelper.addItem(
            wx.CheckBox(self, label=_("Enable streaming"))
        )

        self.progressCheckbox = sHelper.addItem(
            wx.CheckBox(self, label=_("Announce progress"))
        )

        self.modelNameEdit.Value = get_model_name()
        self.serverUrlEdit.Value = get_server_url()
        self.streamingCheckbox.Value = is_streaming_enabled()
        self.progressCheckbox.Value = is_progress_enabled()

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

        set_model_name(modelName)
        set_server_url(serverUrl)
        set_streaming_enabled(self.streamingCheckbox.Value)
        set_progress_enabled(self.progressCheckbox.Value)
        save()
