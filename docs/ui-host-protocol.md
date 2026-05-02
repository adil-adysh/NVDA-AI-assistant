# UI Host Protocol

This document describes the v2 protocol between the NVDA add-on, the Rust UI host, and the WebView UI.

## Goals

- Keep the host boundary generic and implementation-agnostic.
- Send rendering intent, not internal prompt/use-case details.
- Support browseable results, chat opening, errors, progress, and window control.
- Use one self-describing envelope across Python, Rust, and JavaScript.
- Make version mismatches and delivery failures explicit.
- Allow host fallback to native NVDA rendering.

## Message envelope

Each message is a JSON object with a common envelope.

Common fields:

- `schema`: string, currently `nvda.ui_host`
- `version`: integer, currently `2`
- `id`: string, a unique message identifier
- `correlation_id`: string | null, links follow-up events and replies to the original message
- `source`: string, one of `nvda_addon`, `ui_host`, `web_ui`
- `type`: string, one of `command`, `event`, `ack`, `error`

Command messages include:

- `command.name`: string command identifier
- `command.payload`: object payload

Event messages include:

- `event.name`: string event identifier
- `event.payload`: object payload

## Transport model

The protocol is designed around two logical message flows:

1. command flow: add-on to host, request/response
2. event flow: host UI to add-on, asynchronous

The long-term preferred implementation is two logical channels:

- a command channel for `command`, `ack`, and `error`
- an event channel for `event`

If the implementation temporarily uses a single command channel, asynchronous UI events should be delivered through an explicit polling mechanism rather than by assuming a long-lived duplex request connection.

This keeps command acknowledgement and UI-originated event delivery independent as the protocol grows.

## Supported commands

### `render_display`

Payload fields:

- `use_case_id`: string | null
- `title`: string
- `success`: boolean
- `message`: string | null
- `output_text`: string | null
- `output_html`: string | null
- `is_html`: boolean
- `is_browseable`: boolean
- `close_button`: boolean
- `copy_button`: boolean
- `copy_text`: string | null
- `copy_markdown`: string | null
- `actions`: array | null
- `metadata`: object | null

Optional `actions` allow the add-on to attach generic follow-up UI actions to a rendered result.

Example uses:

- opening chat from an image description result
- retrying a failed operation
- opening a follow-up workflow from a summary result

Each action should be treated as opaque by the host UI except for presentation fields. A typical action object may include:

- `id`: string
- `label`: string
- `kind`: string | null
- `payload`: object | null

Optional rich content may also be included for advanced presentation. Two recommended patterns are:

- structured content blocks such as text, thinking trace, warnings, and citations
- typed optional fields for simpler transitional integrations

For thinking-trace support, a result may include fields such as:

- `thinking_trace`: string | null
- `thinking_summary`: string | null
- `thinking_visible_by_default`: boolean | null

The host should treat this as presentation data only. Whether thinking content may be shown is an application decision owned by Python.

Optional presentation metadata may also be included to keep behavior protocol-driven instead of host-specific:

- `interaction_mode`: string, for example `display` or `chat`
- `controls_visible`: boolean
- `attention_policy`: string, for example `none`, `foreground_if_background`, or `activate_and_focus`
- `focus_target`: string, for example `content`, `composer`, `primary_action`, or `status`

Display-oriented results should also prefer an explicit `display_presentation` object in metadata instead of making the Web UI infer layout from unrelated flags.

Recommended `display_presentation` fields:

- `variant`: string, for example `standard` or `result_actions`
- `initial_focus`: string, for example `content` or `primary_action`
- `toolbar`: object with:
  - `actions`: ordered array of toolbar action ids such as `copy_text`, `copy_markdown`, `clear`, `close`
  - `placement`: string, currently `after_content`

Recommended behavior:

- streamed updates should use `attention_policy = none`
- final answers may use `attention_policy = foreground_if_background`
- one-shot result views may hide session controls with `controls_visible = false`
- one-shot result views should use `display_presentation.variant = result_actions`
- one-shot result views can render content plus generic result actions such as `Open Chat` while still placing the secondary toolbar after the content

### `open_chat`

Payload fields:

- `use_case_id`: string | null
- `conversation_id`: string | null
- `title`: string
- `initial_text`: string | null
- `initial_image_base64`: string | null
- `metadata`: object | null

Behavior notes:

- The host should treat `conversation_id` as an opaque identifier owned by Python.
- `initial_image_base64` is optional and should be ignored safely when the active UI cannot display it yet.
- Unknown optional fields in `metadata` must not be required for rendering.

Optional UI state for provider/model controls may also be included. A typical chat payload may carry:

- `provider_state`: object | null
- `available_providers`: array | null
- `available_models`: array | null

This command is the preferred follow-up target for actions such as `Open Chat` from an image description result.

### `chat_set_history`

Payload fields:

- `use_case_id`: string | null
- `conversation_id`: string
- `messages`: array of chat message objects
- `metadata`: object | null

### `chat_append`

Payload fields:

- `use_case_id`: string | null
- `conversation_id`: string
- `message`: chat message object
- `metadata`: object | null

### `chat_update`

Payload fields:

- `use_case_id`: string | null
- `conversation_id`: string
- `message_id`: string
- `content`: string | array
- `status`: string | null
- `metadata`: object | null

### `chat_stream_begin`

Payload fields:

- `use_case_id`: string | null
- `conversation_id`: string
- `message_id`: string
- `stream_id`: string
- `role`: string, typically `assistant`
- `metadata`: object | null

This command starts a streamed chat message without requiring the add-on to resend the full message content on every partial token.
A host-backed UI should treat `stream_id` as the identity of one ordered stream lifecycle for a given `message_id`.

### `chat_stream_delta`

Payload fields:

- `use_case_id`: string | null
- `conversation_id`: string
- `message_id`: string
- `stream_id`: string
- `delta`: string
- `sequence`: integer
- `metadata`: object | null

This command appends an incremental text delta to an in-progress streamed message. The host should treat `sequence` as monotonic and ignore stale deltas when later updates have already been applied.

### `chat_stream_end`

Payload fields:

- `use_case_id`: string | null
- `conversation_id`: string
- `message_id`: string
- `stream_id`: string
- `final_sequence`: integer
- `content`: string | array
- `status`: string | null
- `metadata`: object | null

This command commits the final structured content for a streamed message. It is the point where rich blocks such as HTML, thinking traces, or citations should replace any temporary delta-rendered text.
The host should only finalize a stream when `stream_id` matches the active stream for that message and `final_sequence` is not older than the latest applied delta.

### `chat_stream_abort`

Payload fields:

- `use_case_id`: string | null
- `conversation_id`: string
- `message_id`: string
- `stream_id`: string
- `last_sequence`: integer
- `reason`: string | null
- `metadata`: object | null

This command marks an in-progress streamed message as aborted when the stream cannot be completed in the host projection.

Recommended state machine:

- `chat_stream_begin` starts or replaces the active stream identified by `stream_id`
- `chat_stream_delta` is applied only to the active stream and only when `sequence` is newer than the latest applied delta
- `chat_stream_end` finalizes only the active stream and only when `final_sequence` is at least the latest applied delta sequence
- `chat_stream_abort` aborts only the active stream and only when `last_sequence` is at least the latest applied delta sequence

### `show_error`

Payload fields:

- `error_message`: string
- `details`: string | null

### `update_progress`

Payload fields:

- `stage`: string
- `message`: string

Behavior notes:

- progress updates are informational and should not request foreground or focus changes

### `close_window`

Payload fields:

- `reason`: string | null

Behavior notes:

- native close or hide behavior is owned by the Rust host window layer
- the Web UI may update local status text, but it should not be the source of truth for closing the host

## Failure handling

If the host is unavailable, the add-on must gracefully fall back to the native NVDA UI path.
If the host queue is full or the schema is invalid, the add-on receives an explicit error envelope.

## Versioning and compatibility

The protocol includes `schema` and `version` on every message. The host should ignore unknown optional fields and remain tolerant of additive payload values.
Requests with an unsupported `schema` or `version` are rejected with an `error` response.

## Response and events

The host responds with `ack` or `error` messages on the command flow.

If a dedicated event channel exists, `event` messages should not be multiplexed onto the synchronous command response path.

Ack fields:

- `type`: string, `ack`
- `acked_id`: string, the original request id
- `stage`: string, currently `accepted` or `enqueued`
- `detail`: string | null

Event fields:

- `type`: string, `event`
- `event.name`: string, the event name (`ui_applied`, `ui_failed`, `window_closed`, etc.)
- `event.payload`: object

Error fields:

- `type`: string, `error`
- `failed_id`: string | null
- `code`: string (`invalid_json`, `invalid_schema`, `unsupported_version`, `queue_full`, `ui_dispatch_failed`, ...)
- `detail`: string
- `retriable`: boolean

### `ui_applied`

Event payload fields:

- `command_id`: string | null

### `ui_failed`

Event payload fields:

- `command_id`: string | null
- `reason`: string

### `chat_submitted`

Event payload fields:

- `command_id`: string | null
- `conversation_id`: string | null
- `message`: string

### `ui_action_invoked`

Event payload fields:

- `command_id`: string | null
- `action_id`: string
- `payload`: object | null

This event is used when the WebView renders result-level actions and the user activates one.

For example, an image description result may expose an `Open Chat` action. The host UI emits `ui_action_invoked`, and Python decides whether that should become `open_chat`, `open_chat_with_screenshot`, or another follow-up intent.

### `provider_selected`

Event payload fields:

- `provider`: string

This event is used when the UI allows provider selection and the user picks a different provider.

### `model_selected`

Event payload fields:

- `provider`: string | null
- `model`: string

This event is used when the UI allows model selection and the user picks a different model.

### `think_mode_toggled`

Event payload fields:

- `command_id`: string | null
- `enabled`: boolean

This event is used when the UI allows think-mode toggling and the user changes the value. It is currently consumed by the Python add-on to persist provider-facing configuration.

### `window_closed`

Event payload fields:

- `reason`: string | null

### `web_ui_ready`

Event payload fields:

- none required

This event is emitted by the Web UI after it has attached its host message listener and initialized its bridge.
Rust should treat this as the point where the browser UI is ready for queued host commands.

## Extensibility rules

- The host must ignore unknown fields.
- The add-on may include opaque `metadata` values.
- Addon-specific internal fields should not be required by the host.
- The Rust host normalizes legacy v1 pipe commands into the v2 WebView envelope during migration.
- New commands and events should be added by extending typed payloads, not by changing transport assumptions.
- Python remains the owner of use-case orchestration and conversation state.
- Rust remains the owner of host UI lifecycle and browser event capture.
- Result actions should be generic protocol data, not hardcoded WebView behavior for individual use cases.
- Provider and model choices should be supplied by Python and treated as opaque selectable state by the host UI.
- Thinking trace presentation should be modeled as structured protocol data rather than inferred from raw output text.
- navigation completion alone should not be treated as proof that the Web UI application is ready; prefer an explicit `web_ui_ready` handshake from the browser layer before flushing queued commands.

Current implementation notes:

- Python currently emits presentation intent through metadata in most flows
- the Web UI reads payload and metadata values through shared helpers in `webui/src/lib/bridge.js`
- Rust forwards Web UI event envelopes generically from `webview.rs` to the event pipe, and Python validates and dispatches the event names it consumes
