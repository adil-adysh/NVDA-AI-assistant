// Auto-generated protocol command and event name types.
//
// Generated from ``scripts/protocol.yaml`` by ``scripts/generate_protocol.py``.
// DO NOT EDIT BY HAND.


export type CommandName = "health_check" | "render_display" | "open_chat" | "sync_session" | "chat_set_history" | "chat_append" | "chat_update" | "chat_stream_begin" | "chat_stream_delta" | "chat_stream_end" | "chat_stream_abort" | "show_error" | "update_progress" | "close_window";

export type EventName = "web_ui_ready" | "ui_applied" | "ui_failed" | "window_closed" | "host_log" | "chat_submitted" | "chat_attachment_added" | "chat_closed" | "provider_selected" | "model_selected" | "think_mode_toggled" | "ui_action_invoked" | "close_host";

export const CHAT_COMMANDS = new Set<CommandName>(["open_chat", "chat_set_history", "chat_append", "chat_update", "chat_stream_begin", "chat_stream_delta", "chat_stream_end", "chat_stream_abort"]);

export const COMMAND_REQUIRED_FIELDS: Record<CommandName, readonly string[]> = {
	"health_check": [],
	"render_display": ["title"],
	"open_chat": ["title"],
	"sync_session": [],
	"chat_set_history": ["conversation_id", "messages"],
	"chat_append": ["conversation_id", "message"],
	"chat_update": ["conversation_id", "message_id", "content"],
	"chat_stream_begin": ["message_id", "stream_id"],
	"chat_stream_delta": ["message_id", "stream_id", "delta", "sequence"],
	"chat_stream_end": ["message_id", "stream_id", "final_sequence", "content"],
	"chat_stream_abort": ["message_id", "stream_id", "last_sequence"],
	"show_error": ["error_message"],
	"update_progress": ["stage", "message"],
	"close_window": [],
};

export type PayloadFieldType = 'string' | 'integer' | 'boolean' | 'array' | 'object' | 'json';

export const COMMAND_REQUIRED_FIELD_TYPES: Record<CommandName, Readonly<Record<string, PayloadFieldType>>> = {
	"health_check": {},
	"render_display": {"title": "string"},
	"open_chat": {"title": "string"},
	"sync_session": {},
	"chat_set_history": {"conversation_id": "string", "messages": "array"},
	"chat_append": {"conversation_id": "string", "message": "object"},
	"chat_update": {"conversation_id": "string", "message_id": "string", "content": "json"},
	"chat_stream_begin": {"message_id": "string", "stream_id": "string"},
	"chat_stream_delta": {"message_id": "string", "stream_id": "string", "delta": "string", "sequence": "integer"},
	"chat_stream_end": {"message_id": "string", "stream_id": "string", "final_sequence": "integer", "content": "json"},
	"chat_stream_abort": {"message_id": "string", "stream_id": "string", "last_sequence": "integer"},
	"show_error": {"error_message": "string"},
	"update_progress": {"stage": "string", "message": "string"},
	"close_window": {},
};
