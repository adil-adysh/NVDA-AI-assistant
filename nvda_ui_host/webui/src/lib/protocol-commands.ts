// Auto-generated protocol command and event name types.
//
// Generated from ``scripts/protocol.yaml`` by ``scripts/generate_protocol.py``.
// DO NOT EDIT BY HAND.


export type CommandName = "health_check" | "render_display" | "open_chat" | "sync_session" | "chat_set_history" | "chat_append" | "chat_update" | "chat_stream_begin" | "chat_stream_delta" | "chat_stream_end" | "chat_stream_abort" | "show_error" | "update_progress" | "close_window";

export type EventName = "web_ui_ready" | "ui_applied" | "ui_failed" | "window_closed" | "host_log" | "chat_submitted" | "chat_attachment_added" | "chat_closed" | "provider_selected" | "model_selected" | "think_mode_toggled" | "ui_action_invoked" | "close_host";

export const CHAT_COMMANDS = new Set<CommandName>(["open_chat", "chat_set_history", "chat_append", "chat_update", "chat_stream_begin", "chat_stream_delta", "chat_stream_end", "chat_stream_abort"]);
