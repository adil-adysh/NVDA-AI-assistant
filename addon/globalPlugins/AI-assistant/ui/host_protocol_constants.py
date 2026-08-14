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
EVENT_CLOSE_HOST = "close_host"

COMMAND_NAMES = (
	"health_check",
	"render_display",
	"open_chat",
	"sync_session",
	"chat_set_history",
	"chat_append",
	"chat_update",
	"chat_stream_begin",
	"chat_stream_delta",
	"chat_stream_end",
	"chat_stream_abort",
	"show_error",
	"update_progress",
	"close_window",
)

EVENT_NAMES = (
	"web_ui_ready",
	"ui_applied",
	"ui_failed",
	"window_closed",
	"host_log",
	"chat_submitted",
	"chat_attachment_added",
	"chat_closed",
	"provider_selected",
	"model_selected",
	"think_mode_toggled",
	"ui_action_invoked",
	"close_host",
)

COMMAND_REQUIRED_FIELDS = {
	"health_check": (),
	"render_display": ('title',),
	"open_chat": ('title',),
	"sync_session": (),
	"chat_set_history": ('conversation_id', 'messages'),
	"chat_append": ('conversation_id', 'message'),
	"chat_update": ('conversation_id', 'message_id', 'content'),
	"chat_stream_begin": ('message_id', 'stream_id'),
	"chat_stream_delta": ('message_id', 'stream_id', 'delta', 'sequence'),
	"chat_stream_end": ('message_id', 'stream_id', 'final_sequence', 'content'),
	"chat_stream_abort": ('message_id', 'stream_id', 'last_sequence'),
	"show_error": ('error_message',),
	"update_progress": ('stage', 'message'),
	"close_window": (),
}

COMMAND_REQUIRED_FIELD_TYPES = {
	"health_check": {},
	"render_display": {'title': 'string'},
	"open_chat": {'title': 'string'},
	"sync_session": {},
	"chat_set_history": {'conversation_id': 'string', 'messages': 'array'},
	"chat_append": {'conversation_id': 'string', 'message': 'object'},
	"chat_update": {'conversation_id': 'string', 'message_id': 'string', 'content': 'json'},
	"chat_stream_begin": {'message_id': 'string', 'stream_id': 'string'},
	"chat_stream_delta": {'message_id': 'string', 'stream_id': 'string', 'delta': 'string', 'sequence': 'integer'},
	"chat_stream_end": {'message_id': 'string', 'stream_id': 'string', 'final_sequence': 'integer', 'content': 'json'},
	"chat_stream_abort": {'message_id': 'string', 'stream_id': 'string', 'last_sequence': 'integer'},
	"show_error": {'error_message': 'string'},
	"update_progress": {'stage': 'string', 'message': 'string'},
	"close_window": {},
}