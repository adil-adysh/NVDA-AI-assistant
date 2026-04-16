# -*- coding: utf-8 -*-
from __future__ import annotations

from html import escape as html_escape
from logHandler import log
import threading
from typing import Any

import markdown
import wx

from . import nvda_ui
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

    HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body { font-family: Arial, sans-serif; padding: 12px; line-height: 1.5; background: #ffffff; color: #111; }
#chat { margin: 0; padding: 0; }
.msg { margin-bottom: 18px; }
h4 { font-size: 1rem; font-weight: bold; margin: 0 0 8px 0; }
.bubble { background: #f7f7f7; border-radius: 10px; padding: 12px; border: 1px solid #ddd; }
.msg.user .bubble { border-left: 4px solid #0078d7; }
.msg.assistant .bubble { border-left: 4px solid #333; }
.content { white-space: pre-wrap; word-wrap: break-word; }
pre { background: #eee; padding: 10px; border-radius: 4px; overflow-x: auto; }
code { background: #f2f2f2; padding: 2px 4px; border-radius: 4px; }
blockquote { border-left: 4px solid #ccc; margin: 12px 0; padding-left: 12px; color: #555; }
table { border-collapse: collapse; width: 100%; margin-top: 10px; }
td, th { border: 1px solid #999; padding: 6px 10px; }
a { color: #0066cc; text-decoration: none; }
a:hover { text-decoration: underline; }
</style>
</head>
<body>
<div id="chat" role="log" aria-live="polite"></div>
</body>
</html>
"""

    def _build_ui(self) -> None:
        mainSizer = wx.BoxSizer(wx.VERTICAL)

        headerLabel = wx.StaticText(self, label=_("AI Chat"))
        headerFont = headerLabel.Font
        headerFont = headerFont.Bold()
        headerLabel.SetFont(headerFont)
        mainSizer.Add(headerLabel, 0, wx.ALL | wx.EXPAND, 10)

        historyLabel = wx.StaticText(self, label=_("Conversation history is displayed in browse mode."))
        mainSizer.Add(historyLabel, 0, wx.ALL | wx.EXPAND, 10)

        self.historyButton = wx.Button(self, label=_("Show history"))
        self.historyButton.Bind(wx.EVT_BUTTON, self.on_show_history)
        mainSizer.Add(self.historyButton, 0, wx.ALL, 10)

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

    def _build_history_page(self, messages: list[Any]) -> str:
        rows: list[str] = []
        for msg in messages:
            role = msg.role if msg.role in {"user", "assistant", "system", "tool"} else "assistant"
            label = "User" if role == "user" else "Assistant" if role == "assistant" else msg.role.capitalize()
            content = msg.content or ""
            if role == "tool":
                label = f"Tool/{msg.tool_name or 'tool'}"
            rows.append(
                f"<div class='msg {role}'><h4>{self._escape_html(label)}</h4>"
                f"<div class='bubble content'>{self._render_message_html(content)}</div></div>"
            )
        html = self.HTML_TEMPLATE.replace("<div id=\"chat\" role=\"log\" aria-live=\"polite\"></div>", "<div id=\"chat\" role=\"log\" aria-live=\"polite\">" + "".join(rows) + "</div>")
        return html

    def _render_message_html(self, content: str) -> str:
        if not content:
            return ""

        return markdown.markdown(
            content,
            extensions=["extra", "sane_lists", "smarty"],
            output_format="html5",
        )

    def _escape_html(self, text: str) -> str:
        return html_escape(text)

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

        nvda_ui.message(_("Sending message..."))
        tool_call_enabled = self.toolCheckbox.Value
        tools = self._get_tool_definitions() if tool_call_enabled else None
        image_base64 = self._attached_image_base64
        self._set_status(_("Sending..."))
        self._set_ui_enabled(False)

        thread = threading.Thread(
            target=self._send_message,
            args=(message, image_base64, tools, tool_call_enabled),
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

    def _send_message(
        self,
        message: str,
        image_base64: str | None,
        tools: list[dict[str, Any]] | None,
        tool_call_enabled: bool,
    ) -> None:
        log.debug(
            "ChatDialog._send_message: message=%r tool_call_enabled=%s tool_names=%s",
            message,
            tool_call_enabled,
            [tool.get("function", {}).get("name") for tool in tools] if tools else None,
        )
        try:
            response_text = self._coordinator.send_message(
                message,
                image_base64=image_base64,
                progress_callback=self._on_progress,
                tools=tools,
            )
        except Exception as error:
            error_text = str(error)
            wx.CallAfter(self._set_status, _("Error sending message"))
            wx.CallAfter(wx.MessageBox, error_text, _("AI Chat Error"), wx.OK | wx.ICON_ERROR)
        else:
            wx.CallAfter(self.inputCtrl.SetValue, "")
            wx.CallAfter(self._refresh_history)
            wx.CallAfter(self._display_last_turn, message, response_text)
            wx.CallAfter(self._set_status, _("Ready"))
            self._attached_image_base64 = None
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

    def _append_local_history(self, role: str, content: str, tool_name: str | None = None, image_attached: bool = False) -> None:
        self._refresh_history()

    def _refresh_history(self) -> None:
        messages = self._coordinator.get_history()
        self._history_html = self._build_history_page(messages)

    def _show_history(self) -> None:
        if not getattr(self, "_history_html", None):
            self._refresh_history()
        title = nvda_ui.format_browseable_title(_("AI Chat History"), self._provider_state)
        nvda_ui.browseable_message(
            self._history_html,
            title=title,
            is_html=True,
            close_button=True,
            copy_button=True,
        )

    def _display_last_turn(self, user_message: str, assistant_message: str) -> None:
        html = self._build_last_turn_html(user_message, assistant_message)
        title = nvda_ui.format_browseable_title(_("Response Preview"), self._provider_state)
        nvda_ui.browseable_message(
            html,
            title=title,
            is_html=True,
            close_button=True,
            copy_button=True,
        )

    def _build_last_turn_html(self, user_message: str, assistant_message: str) -> str:
        user_html = self._render_message_html(user_message)
        assistant_html = self._render_message_html(assistant_message)
        return (
            "<!DOCTYPE html>"
            "<html><head><meta charset=\"utf-8\"><style>"
            "body{font-family:Arial,sans-serif;padding:16px;line-height:1.6;color:#111;}"
            ".section{margin-bottom:18px;}"
            "h4{font-size:1rem;font-weight:bold;margin:0 0 8px 0;}"
            ".bubble{background:#f7f7f7;border-radius:10px;padding:12px;border:1px solid #ddd;}"
            "</style></head><body>"
            "<div class=\"section\"><h4>User query</h4>"
            f"<div class=\"bubble\">{user_html}</div></div>"
            "<div class=\"section\"><h4>Assistant response</h4>"
            f"<div class=\"bubble\">{assistant_html}</div></div>"
            "</body></html>"
        )

    def on_show_history(self, event: Any) -> None:
        self._show_history()

    def _get_tool_definitions(self) -> list[dict[str, Any]]:
        return self._tool_registry.get_definitions()
