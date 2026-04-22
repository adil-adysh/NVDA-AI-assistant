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
- `copy_html`: string | null
- `metadata`: object | null

### `open_chat`

Payload fields:
- `use_case_id`: string | null
- `title`: string
- `initial_text`: string | null
- `initial_image_base64`: string | null
- `metadata`: object | null

### `show_error`

Payload fields:
- `error_message`: string
- `details`: string | null

### `update_progress`

Payload fields:
- `stage`: string
- `message`: string

### `close_window`

Payload fields:
- `reason`: string | null

## Failure handling

If the host is unavailable, the add-on must gracefully fall back to the native NVDA UI path.
If the host queue is full or the schema is invalid, the add-on receives an explicit error envelope.

## Versioning and compatibility

The protocol includes `schema` and `version` on every message. The host should ignore unknown optional fields and remain tolerant of additive payload values.
Requests with an unsupported `schema` or `version` are rejected with an `error` response.

## Response and events

The host responds with `ack` or `error` messages on the same pipe connection.

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

### `window_closed`

Event payload fields:
- `reason`: string | null

## Extensibility rules

- The host must ignore unknown fields.
- The add-on may include opaque `metadata` values.
- Addon-specific internal fields should not be required by the host.
- The Rust host normalizes legacy v1 pipe commands into the v2 WebView envelope during migration.
