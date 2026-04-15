# -*- coding: utf-8 -*-
from __future__ import annotations

from logHandler import log
import threading
from typing import Any

import wx

from ..config.state import ProviderState
from ..service import ChatCoordinator
from ..tools import ToolRegistry

chatDialogInstance = None


class ChatDialog(wx.Dialog):
    def __init__(
        self,
        parent: wx.Window | None,
        coordinator: ChatCoordinator,
        tool_registry: ToolRegistry,
        provider_state: ProviderState,
        initial_text: str | None = None,
        initial_image_base64: str | None = None,
    ) -> None:
        super().__init__(parent, title=_("AI Chat"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._coordinator = coordinator
        self._tool_registry = tool_registry
        self._provider_state = provider_state
        self._attached_image_base64 = initial_image_base64
        self._build_ui()
        self._refresh_provider_title()
        self._refresh_history()
        if initial_text:
            self.inputCtrl.SetValue(initial_text)
        if initial_image_base64:
            self._set_status(_("Screenshot attached to the initial chat."))
        self.SetMinSize((640, 520))
        self.CenterOnScreen()

    def set_initial_state(self, initial_text: str | None = None, initial_image_base64: str | None = None) -> None:
        if initial_text is not None:
            self.inputCtrl.SetValue(initial_text)
        self._attached_image_base64 = initial_image_base64
        if initial_image_base64:
            self._set_status(_("Screenshot attached to the initial chat."))

    def update_provider_state(self, provider_state: ProviderState) -> None:
        self._provider_state = provider_state
        self._refresh_provider_title()

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

        self.inputCtrl = wx.TextCtrl(
            self,
            style=wx.TE_MULTILINE | wx.HSCROLL | wx.VSCROLL,
        )
        self.inputCtrl.SetMinSize((620, 120))
        self.inputCtrl.Bind(wx.EVT_KEY_DOWN, self.on_input_key_down)
        self.inputCtrl.SetToolTip(_("Type a message. Press Ctrl+Enter to send or click Send."))
        mainSizer.Add(self.inputCtrl, 0, wx.ALL | wx.EXPAND, 10)

        self.toolCheckbox = wx.CheckBox(self, label=_("Enable tool calling"))
        supported_tools = ", ".join(self._tool_registry.get_tool_names()) or _("none")
        self.toolCheckbox.SetToolTip(_("Allow the model to call available tools: {tools}." ).format(tools=supported_tools))
        self.toolCheckbox.SetValue(True)
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

    def _refresh_provider_title(self) -> None:
        provider = self._provider_state.provider.strip()
        model_name = self._provider_state.model_name.strip()
        title = _("AI Chat")
        if provider:
            provider_label = provider.capitalize()
            if model_name:
                title = f"{title} — {provider_label} ({model_name})"
            else:
                title = f"{title} — {provider_label}"
        self.SetTitle(title)

    def refresh_provider_title(self) -> None:
        self._refresh_provider_title()

    def on_input_key_down(self, event: Any) -> None:
        if event.ControlDown() and event.KeyCode == wx.WXK_RETURN:
            self.on_send(event)
        else:
            event.Skip()

    def on_send(self, event: Any) -> None:
        message = self.inputCtrl.Value.strip()
        if not message and not self._attached_image_base64:
            return

        self.inputCtrl.Value = ""
        self._append_local_history("User", message, image_attached=bool(self._attached_image_base64))
        self._set_status(_("Sending..."))
        self._set_ui_enabled(False)

        thread = threading.Thread(
            target=self._send_message,
            args=(message,),
            daemon=True,
        )
        thread.start()

    def on_clear(self, event: Any) -> None:
        self._coordinator.reset()
        self._attached_image_base64 = None
        self.inputCtrl.Value = ""
        self._refresh_history()
        self._set_status(_("Ready"))
        self._set_ui_enabled(True)

    def on_close(self, event: Any) -> None:
        self.Destroy()

    def onDestroy(self, evt: Any) -> None:
        global chatDialogInstance
        chatDialogInstance = None
        evt.Skip()

    def _send_message(self, message: str) -> None:
        tools = self._get_tool_definitions() if self.toolCheckbox.Value else None
        log.debug(
            "ChatDialog._send_message: message=%r tool_call_enabled=%s tool_names=%s",
            message,
            self.toolCheckbox.Value,
            [tool.get("function", {}).get("name") for tool in tools] if tools else None,
        )
        image_base64 = self._attached_image_base64
        try:
            self._coordinator.send_message(
                message,
                image_base64=image_base64,
                progress_callback=self._on_progress,
                tools=tools,
            )
        except Exception as error:
            error_text = str(error)
            wx.CallAfter(self._append_local_history, "Error", error_text)
            wx.CallAfter(self._set_status, _("Error sending message"))
            wx.CallAfter(wx.MessageBox, error_text, _("AI Chat Error"), wx.OK | wx.ICON_ERROR)
        else:
            wx.CallAfter(self._refresh_history)
            wx.CallAfter(self._set_status, _("Ready"))
        finally:
            self._attached_image_base64 = None
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

    def _append_local_history(self, role: str, content: str, tool_name: str | None = None, image_attached: bool = False) -> None:
        if role == "User" and image_attached:
            label = _("User (image attached): ")
            if not content:
                content = _("[Image only]")
        elif role == "Tool":
            label = f"{role}/{tool_name or 'unknown'}: "
        else:
            label = f"{role}: "
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
        return self._tool_registry.get_definitions()
