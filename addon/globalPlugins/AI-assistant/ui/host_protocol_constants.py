# -*- coding: utf-8 -*-
"""Auto-generated protocol command and event name constants.

Generated from ``scripts/protocol.yaml`` by ``scripts/generate_protocol.py``.
DO NOT EDIT BY HAND.
"""
from __future__ import annotations


COMMAND_HEALTH_CHECK = "health_check"
COMMAND_RENDER_DISPLAY = "render_display"
COMMAND_OPEN_CHAT = "open_chat"
COMMAND_SYNC_SESSION = "sync_session"
COMMAND_CHAT_SET_HISTORY = "chat_set_history"
COMMAND_CHAT_APPEND = "chat_append"
COMMAND_CHAT_UPDATE = "chat_update"
COMMAND_CHAT_STREAM_BEGIN = "chat_stream_begin"
COMMAND_CHAT_STREAM_DELTA = "chat_stream_delta"
COMMAND_CHAT_STREAM_END = "chat_stream_end"
COMMAND_CHAT_STREAM_ABORT = "chat_stream_abort"
COMMAND_SHOW_ERROR = "show_error"
COMMAND_UPDATE_PROGRESS = "update_progress"
COMMAND_CLOSE_WINDOW = "close_window"

EVENT_WEB_UI_READY = "web_ui_ready"
EVENT_UI_APPLIED = "ui_applied"
EVENT_UI_FAILED = "ui_failed"
EVENT_WINDOW_CLOSED = "window_closed"
EVENT_HOST_LOG = "host_log"
EVENT_CHAT_SUBMITTED = "chat_submitted"
EVENT_CHAT_ATTACHMENT_ADDED = "chat_attachment_added"
EVENT_CHAT_CLOSED = "chat_closed"
EVENT_PROVIDER_SELECTED = "provider_selected"
EVENT_MODEL_SELECTED = "model_selected"
EVENT_THINK_MODE_TOGGLED = "think_mode_toggled"
EVENT_UI_ACTION_INVOKED = "ui_action_invoked"
EVENT_ESCAPE_PRESSED = "escape_pressed"
EVENT_CLOSE_HOST = "close_host"
