# Protocol Contract Spec

> **Purpose**: Single source of truth for all protocol commands, events, envelope shape, and version rules.
> **Maintainers**: When adding/changing a command or event, update this spec BEFORE updating Python, Rust, or TypeScript code.
> **Generated from**: This spec is the canonical definition. Code generation targets Python (`host_protocol.py` constants), Rust (`protocol.rs` enums), and TypeScript (`protocol-types.ts` interfaces).

## Envelope

All messages share a common envelope:

```json
{
  "schema": "nvda.ui_host",
  "version": 2,
  "id": "<unique-message-id>",
  "correlation_id": "<optional-correlation-id>",
  "source": "nvda_addon | ui_host | web_ui",
  "type": "command | event | ack | error"
}
```

### Rules

- `schema` MUST be `"nvda.ui_host"`, `version` MUST be `2`.
- `id` is a unique opaque string per message.
- `correlation_id` links follow-ups to the originating message.
- `source` identifies the sender layer.
- `type` determines the body shape (see below).

### Message types

| type | body shape | direction |
|------|-----------|-----------|
| `command` | `{ "command": { "name": "...", "payload": {...} } }` | addon → host → webui |
| `event` | `{ "event": { "name": "...", "payload": {...} } }` | webui → host → addon |
| `ack` | `{ "acked_id": "...", "stage": "accepted|enqueued|dispatched_to_ui", "detail": "..." }` | host → addon |
| `error` | `{ "failed_id": "...", "code": "...", "detail": "...", "retriable": bool }` | host → addon |

## Commands

All flow: Python addon → Rust host → WebView UI.

| name | payload fields | activation policy | notes |
|------|---------------|-------------------|-------|
| `health_check` | *(none)* | none | Returns ack immediately |
| `render_display` | `use_case_id`, `title`, `success`, `message`, `output_text`, `output_html`, `is_html`, `is_browseable`, `close_button`, `copy_button`, `copy_text`, `copy_markdown`, `actions[]`, `metadata{}` | foreground_if_background | Display-only result view |
| `open_chat` | `use_case_id`, `conversation_id`, `title`, `initial_text`, `initial_image_base64`, `metadata{}` | activate_and_focus | Opens chat view |
| `sync_session` | `metadata{}` (provider_state, available_providers, available_models, conversation_summaries, localized_strings, think_enabled, chat_enabled, provider_status) | none | Syncs session state without changing view |
| `chat_set_history` | `use_case_id`, `conversation_id`, `messages[]` | none | Bulk-set conversation history |
| `chat_append` | `use_case_id`, `conversation_id`, `message{}` (id, role, content) | none (activate_if_background on final) | Append single message |
| `chat_update` | `use_case_id`, `conversation_id`, `message_id`, `content`, `status`, `metadata{}` | none | Full-message replacement |
| `chat_stream_begin` | `use_case_id`, `conversation_id`, `message_id`, `stream_id`, `role`, `metadata{}` | none | Start streaming token sequence |
| `chat_stream_delta` | `use_case_id`, `conversation_id`, `message_id`, `stream_id`, `delta`, `sequence` | none | Append tokens to streaming message |
| `chat_stream_end` | `use_case_id`, `conversation_id`, `message_id`, `stream_id`, `final_sequence`, `content[]`, `metadata{}` | foreground_if_background | Finalize streamed message |
| `chat_stream_abort` | `use_case_id`, `conversation_id`, `message_id`, `stream_id`, `final_sequence`, `reason` | none | Abort streamed message |
| `show_error` | `use_case_id`, `title`, `message`, `is_fatal`, `retriable`, `metadata{}` | foreground_if_background | Display error view |
| `update_progress` | `use_case_id`, `stage`, `message`, `progress` | none | Update progress indicator |
| `close_window` | `reason` | none | Close the host window |

## Events

All flow: WebView UI → Rust host → Python addon.

| name | payload fields | notes |
|------|---------------|-------|
| `web_ui_ready` | *(none)* | WebView initialized, ready for commands |
| `ui_applied` | `command_id` | Command successfully applied in UI |
| `ui_failed` | `command_id`, `reason` | Command failed in UI |
| `window_closed` | `reason` | User closed the window |
| `host_log` | `level`, `message` | Log message from host |
| `chat_submitted` | `conversation_id`, `text`, `attachments[]`, `metadata{}` | User submitted chat message |
| `chat_attachment_added` | `conversation_id`, `attachment{}` | File/image attached to chat |
| `chat_closed` | `conversation_id`, `reason` | Chat view closed |
| `provider_selected` | `provider` | User changed provider |
| `model_selected` | `provider`, `model` | User changed model |
| `think_mode_toggled` | `enabled` | User toggled think mode |
| `ui_action_invoked` | `action_id`, `payload{}` | User invoked a result action |
| `escape_pressed` | *(none)* | User pressed Escape |
| `close_host` | *(none)* | WebView requested host close |

## Presentation Metadata

Shared metadata fields passed in command payloads (via `metadata{}` and/or top-level fields):

| field | type | values | notes |
|-------|------|--------|-------|
| `interaction_mode` | string | `"display"`, `"chat"` | Which view mode to enter |
| `controls_visible` | boolean | | Whether provider/model controls are shown |
| `attention_policy` | string | `"none"`, `"foreground_if_background"`, `"activate_and_focus"` | Window activation behavior |
| `focus_target` | string | `"content"`, `"composer"`, `"primary_action"`, `"status"` | Which element to focus after render |
| `display_presentation` | object | `{ variant, toolbar, initial_focus }` | Display-specific layout options |
| `display_presentation.variant` | string | `"standard"`, `"result_actions"` | Display layout variant |
| `display_presentation.toolbar.actions` | string[] | `"copy_text"`, `"copy_markdown"`, `"clear"`, `"close"` | Toolbar action buttons |
| `display_presentation.toolbar.placement` | string | `"after_content"` | Toolbar position |
| `display_presentation.initial_focus` | string | same as `focus_target` | Override focus for display views |
| `localized_strings` | object | `{ key: value }` | Python-supplied UI labels |
| `status_message` | string | | Temporary status banner text |
| `provider_state` | object | `{ provider, model }` | Active provider/model |
| `provider_status` | object | `{ state, reason, can_infer, can_list_models }` | Provider readiness |
| `available_providers` | array | `[{ id, label }]` | Selectable providers |
| `available_models` | string[] | | Selectable model names |
| `think_enabled` | boolean | | Think mode toggle state |
| `chat_enabled` | boolean | | Whether chat submission is allowed |
| `conversation_summaries` | array | `[{ id, title, preview, message_count, updated_at }]` | Saved conversations |
