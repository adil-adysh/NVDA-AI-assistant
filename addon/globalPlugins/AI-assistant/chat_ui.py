# -*- coding: utf-8 -*-
from __future__ import annotations

import threading
from typing import Any

import wx

from .chat_coordinator import ChatCoordinator

chatDialogInstance = None


class ChatDialog(wx.Dialog):
    def __init__(self, parent: wx.Window | None, coordinator: ChatCoordinator) -> None:
        super().__init__(parent, title=_("AI Chat"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._coordinator = coordinator
        self._build_ui()
        self._refresh_history()
        self.SetMinSize((640, 520))
        self.CenterOnScreen()

    def _build_ui(self) -> None:
        mainSizer = wx.BoxSizer(wx.VERTICAL)

        headerLabel = wx.StaticText(self, label=_("AI Chat"))
        headerFont = headerLabel.Font
        headerFont = headerFont.Bold()
        headerLabel.SetFont(headerFont)
        mainSizer.Add(headerLabel, 0, wx.ALL | wx.EXPAND, 10)

        self.historyCtrl = wx.TextCtrl(
            self,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL | wx.VSCROLL,
        )
        self.historyCtrl.SetBackgroundColour(self.GetBackgroundColour())
        self.historyCtrl.SetMinSize((620, 320))

        mainSizer.Add(wx.StaticText(self, label=_("Conversation history:")), 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        mainSizer.Add(self.historyCtrl, 1, wx.ALL | wx.EXPAND, 10)

        inputLabel = wx.StaticText(self, label=_("Message:"))
        mainSizer.Add(inputLabel, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        self.inputCtrl = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.inputCtrl.Bind(wx.EVT_TEXT_ENTER, self.on_send)
        self.inputCtrl.SetToolTip(_("Type a message and press Enter or click Send."))
        mainSizer.Add(self.inputCtrl, 0, wx.ALL | wx.EXPAND, 10)

        self.toolCheckbox = wx.CheckBox(self, label=_("Enable get_time tool calling"))
        self.toolCheckbox.SetToolTip(_("Allow the model to call the built-in get_time tool."))
        mainSizer.Add(self.toolCheckbox, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        buttonSizer = wx.BoxSizer(wx.HORIZONTAL)
        self.sendButton = wx.Button(self, label=_("Send"))
        self.clearButton = wx.Button(self, label=_("Clear"))
        self.closeButton = wx.Button(self, label=_("Close"))

        self.sendButton.Bind(wx.EVT_BUTTON, self.on_send)
        self.clearButton.Bind(wx.EVT_BUTTON, self.on_clear)
        self.closeButton.Bind(wx.EVT_BUTTON, self.on_close)

        buttonSizer.Add(self.sendButton, 0, wx.RIGHT, 5)
        buttonSizer.Add(self.clearButton, 0, wx.RIGHT, 5)
        buttonSizer.AddStretchSpacer(1)
        buttonSizer.Add(self.closeButton, 0, wx.LEFT, 5)
        mainSizer.Add(buttonSizer, 0, wx.ALL | wx.EXPAND, 10)

        self.statusLabel = wx.StaticText(self, label=_("Ready"))
        mainSizer.Add(self.statusLabel, 0, wx.ALL | wx.EXPAND, 10)

        self.SetSizer(mainSizer)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.onDestroy)

    def on_send(self, event: Any) -> None:
        message = self.inputCtrl.Value.strip()
        if not message:
            return

        self.inputCtrl.Value = ""
        self._append_local_history("User", message)
        self._set_status(_("Sending..."))
        self._set_ui_enabled(False)

        thread = threading.Thread(target=self._send_message, args=(message,), daemon=True)
        thread.start()

    def on_clear(self, event: Any) -> None:
        self._coordinator.reset()
        self._refresh_history()
        self._set_status(_("Ready"))

    def on_close(self, event: Any) -> None:
        self.Close()

    def onDestroy(self, evt: Any) -> None:
        global chatDialogInstance
        chatDialogInstance = None
        evt.Skip()

    def _send_message(self, message: str) -> None:
        tools = self._get_tool_definitions() if self.toolCheckbox.Value else None
        try:
            self._coordinator.send_message(message, progress_callback=self._on_progress, tools=tools)
        except Exception as error:
            wx.CallAfter(self._append_local_history, "Error", str(error))
            wx.CallAfter(self._set_status, _("Error sending message"))
        else:
            wx.CallAfter(self._refresh_history)
            wx.CallAfter(self._set_status, _("Ready"))
        finally:
            wx.CallAfter(self._set_ui_enabled, True)

    def _on_progress(self, partial_text: str, generated_chars: int) -> None:
        wx.CallAfter(self._set_status, _(f"Receiving response ({generated_chars} chars)..."))

    def _set_status(self, text: str) -> None:
        self.statusLabel.Label = text

    def _set_ui_enabled(self, enabled: bool) -> None:
        self.sendButton.Enable(enabled)
        self.clearButton.Enable(enabled)
        self.closeButton.Enable(enabled)
        self.inputCtrl.Enable(enabled)

    def _append_local_history(self, role: str, content: str, tool_name: str | None = None) -> None:
        label = f"{role}: " if role != "Tool" else f"{role}/{tool_name or 'unknown'}: "
        self.historyCtrl.AppendText(f"{label}{content}\n")
        self.historyCtrl.ShowPosition(self.historyCtrl.GetLastPosition())

    def _refresh_history(self) -> None:
        messages = self._coordinator.get_history()
        lines: list[str] = []
        for msg in messages:
            if msg.role == "tool":
                label = f"Tool/{msg.tool_name or 'tool'}: "
            else:
                label = f"{msg.role.capitalize()}: "
            lines.append(f"{label}{msg.content or ''}")
        self.historyCtrl.ChangeValue("\n".join(lines) + ("\n" if lines else ""))
        self.historyCtrl.ShowPosition(self.historyCtrl.GetLastPosition())

    def _get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_time",
                    "description": "Get the current local date and time.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            }
        ]
