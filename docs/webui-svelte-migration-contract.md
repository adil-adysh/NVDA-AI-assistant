# WebUI Svelte Migration Contract

This document freezes the current browser-side contract that the Svelte 5 refactor must preserve.

It is intentionally narrower than a full architecture doc and more concrete than a design plan. The goal is to make the migration safe by preserving the existing host protocol, user-visible behavior, and accessibility guarantees while allowing the implementation to move from imperative DOM code to Svelte components and stores.

## Scope

This contract applies to the WebView UI implementation currently sourced from `nvda_ui_host/webui/src/` and embedded by the Rust host.

It covers:

- embedded asset expectations
- inbound command handling
- outbound UI event emission
- payload and content shaping rules already relied on by Python and Rust
- keyboard, focus, copy, and attachment behavior

It does not require the Svelte rewrite to preserve the current DOM ids, module boundaries, or imperative rendering strategy.

## Source of truth

The migration must preserve behavior described by these existing sources:

- `docs/ui-host-protocol.md`
- `nvda_ui_host/src/protocol.rs`
- `nvda_ui_host/src/webview.rs`
- `nvda_ui_host/webui/src/App.svelte`
- `nvda_ui_host/webui/src/lib/bridge.ts`
- `nvda_ui_host/webui/src/lib/commands/`
- `nvda_ui_host/webui/src/lib/operations/`
- `nvda_ui_host/webui/src/lib/state.svelte.ts`
- `nvda_ui_host/webui/src/lib/transcript.svelte.ts`
- `nvda_ui_host/webui/src/lib/protocol-types.ts`
- `nvda_ui_host/webui/src/lib/actions.ts`
- `nvda_ui_host/webui/src/lib/content.ts`
- `nvda_ui_host/webui/src/lib/attachments.ts`
- `addon/globalPlugins/AI-assistant/ui/host_protocol.py`
- `addon/globalPlugins/AI-assistant/ui/host_renderer.py`

If the Svelte implementation and any of the sources above disagree, preserve the currently shipped runtime behavior unless the protocol is explicitly changed in Python, Rust, and documentation together.

## Non-negotiable asset contract

The Rust host embeds static assets via `include_str!` and expects these exact files to exist:

- `nvda_ui_host/assets/host.html`
- `nvda_ui_host/assets/host.js`
- `nvda_ui_host/assets/host.css`

The Svelte build may change how those files are produced, but it must continue to generate equivalent embedded assets at those exact paths unless the Rust host is updated in the same change.

## Protocol envelope contract

The WebView must continue to accept and emit v2 envelopes using:

- `schema = "nvda.ui_host"`
- `version = 2`
- `type` values compatible with `command` and `event`

Inbound messages with invalid schema, unsupported version, or unexpected type must continue to produce a visible status update and a `ui_failed` event where the current implementation does so.

The browser-side implementation must remain tolerant of additive payload fields and unknown optional metadata.

## Inbound command contract

The WebView must continue to handle these command names:

- `render_display`
- `open_chat`
- `sync_session`
- `chat_set_history`
- `chat_append`
- `chat_update`
- `chat_stream_begin`
- `chat_stream_delta`
- `chat_stream_end`
- `chat_stream_abort`
- `show_error`
- `update_progress`
- `close_window`

### `render_display`

Required preserved behavior:

- switches the UI to display mode
- clears chat state for the current view
- stores `copy_text` and `copy_markdown` when supplied
- renders either rich HTML or plain text content
- renders result actions when provided in `actions` or `metadata.actions`
- supports optional thinking content using fields such as `thinking_trace`, `thinking_summary`, and `thinking_visible_by_default`
- updates the window title when `payload.title` is present
- queues focus to the first result action when actions exist, otherwise to content

### `open_chat`

Required preserved behavior:

- switches the UI to chat mode
- clears display state for the current view
- stores `commandId` and `conversationId`
- initializes chat history from `initial_text` when provided
- adds an initial image attachment when `initial_image_base64` is provided
- copies provider and model selector state from `provider_state`, `available_providers`, `available_models`, and `think_enabled` when present
- defaults copy buffers from `initial_text` when available

### `sync_session`

Required preserved behavior:

- updates `conversation_id` when present
- refreshes the currently active view without changing view mode

### `chat_set_history`

Required preserved behavior:

- sets chat mode active
- replaces the current message list with the provided `messages`
- preserves `conversation_id` and optional `command_id`

### `chat_append`

Required preserved behavior:

- ensures chat mode is active
- accepts either `payload.messages`, `payload.message`, or a payload shaped as a single message
- updates `conversation_id` and `command_id` when present
- de-duplicates by `message.id` before appending
- scrolls chat content to the bottom after append

### `chat_update`

Required preserved behavior:

- locates a message using `message_id` or `id`
- replaces message content in place
- updates `conversation_id` and `command_id` when present
- re-renders chat mode and keeps chat scrolling behavior intact

This command remains the non-streaming full-message replacement path.

### `chat_stream_begin`

Required preserved behavior:

- ensures chat mode is active
- creates or reuses an in-progress message keyed by `message_id`
- preserves `conversation_id` when present
- initializes temporary streaming state without requiring final rich content yet

### `chat_stream_delta`

Required preserved behavior:

- appends only the incremental `delta` text to the in-progress message keyed by `message_id`
- ignores stale deltas when `sequence` is older than the last applied update for that message
- preserves `conversation_id` when present
- keeps chat scrolling behavior intact while the message is streaming

### `chat_stream_end`

Required preserved behavior:

- locates the in-progress message using `message_id`
- replaces temporary streamed text with final `content`
- clears temporary streaming state for that message
- preserves `conversation_id` and focus-target behavior when present

### `chat_stream_abort`

Required preserved behavior:

- locates the in-progress message using `message_id`
- marks the message as no longer streaming
- tolerates missing or already-finalized messages without crashing the UI

### `show_error`

Required preserved behavior:

- clears chat mode state from the current view
- displays the error using the `error_prefix` localized string
- includes optional `details` text in the display body
- updates both copy buffers with the error text
- updates status with a short error summary

### `update_progress`

Required preserved behavior:

- clears chat mode state from the current view
- shows progress text using localized progress labels
- updates both copy buffers with the progress message when available
- updates status with the progress summary

### `close_window`

Required preserved behavior:

- clears chat mode state from the current view
- shows the localized closed-window message
- clears both copy buffers
- updates status to the same closed-window message

## Outbound event contract

The WebView must continue to emit v2 `event` envelopes with `source = "web_ui"`.

The current implementation emits more event names than the narrowed Rust enum in `nvda_ui_host/src/protocol.rs`. The migration must preserve the actual browser behavior relied on by Python and `webview.rs`.

### Events emitted by the current WebView

- `ui_applied`
- `ui_failed`
- `close_host`
- `chat_submitted`
- `provider_selected`
- `model_selected`
- `think_mode_toggled`
- `ui_action_invoked`
- `escape_pressed` is treated equivalently to close intent on the Rust side and may remain internal or explicit, but closing via Escape must continue to work

### Common event envelope rules

Required preserved behavior:

- event ids remain unique per emission
- `correlation_id` is set from the active command id when available
- event payloads include `command_id` for events that currently send it
- outbound events are serialized through the WebView bridge using `window.chrome.webview.postMessage(JSON.stringify(payload))`

### `ui_applied`

Payload contract:

- `command_id: string | null`

Behavior contract:

- emitted after a supported command is successfully applied to the UI

### `ui_failed`

Payload contract:

- `command_id: string | null`
- `reason: string`

Behavior contract:

- emitted for invalid schema, unsupported version, unexpected message type, invalid JSON, handler exceptions, and unknown commands as done today

### `close_host`

Payload contract:

- currently empty aside from `command_id: null`

Behavior contract:

- emitted when the user presses the Close button
- must continue to trigger host window close behavior through `webview.rs`

### `chat_submitted`

Payload contract:

- `command_id: string | null`
- `conversation_id: string | null`
- `message: string`
- `attachments: array`

Behavior contract:

- emitted only when a non-empty trimmed message exists or attachments are present
- submission clears the composer text and pending attachments after emission

### `provider_selected`

Payload contract:

- `command_id: string | null`
- `provider: string`

Behavior contract:

- emitted when the provider selector changes to a non-empty value

### `model_selected`

Payload contract:

- `command_id: string | null`
- `provider: string | null`
- `model: string`

Behavior contract:

- emitted from either manual text entry or model select choice
- selecting a model from the select mirrors the value into the text input before emitting

### `think_mode_toggled`

Payload contract:

- `command_id: string | null`
- `enabled: boolean`

Behavior contract:

- emitted whenever the think-mode checkbox changes

### `ui_action_invoked`

Payload contract:

- `command_id: string | null`
- `action_id: string`
- `payload: object | null`

Behavior contract:

- emitted when a rendered result action is activated
- JSON payload parsing remains tolerant of invalid `data-action-payload`, defaulting to `{}` in the current implementation

## Attachment contract

The Svelte rewrite must preserve the current attachment data shapes emitted in `chat_submitted` payloads.

### Image attachment shape

- `id: string`
- `kind: "image"`
- `name: string`
- `mime_type: string`
- `image_base64: string`

### Text file attachment shape

- `id: string`
- `kind: "file"`
- `name: string`
- `mime_type: string`
- `text: string`

### Attachment processing rules

Required preserved behavior:

- image files are read as data URLs and emitted as base64 without the data-url prefix
- known text files are read as text and emitted as plain text payloads
- unsupported files produce a status failure update and are not attached
- removing an attachment returns focus to the composer
- clearing pending attachments resets the hidden file input value

## Copy and content extraction contract

The current implementation exposes two global copy actions and message-level copy actions. The Svelte rewrite must preserve their outputs.

### Global copy behavior

Required preserved behavior:

- `Copy text` copies `copyText` when explicitly provided, otherwise falls back to extracted plain text from the active view
- `Copy markdown` copies `copyMarkdown` when explicitly provided, otherwise falls back to markdown extracted from the active view
- copy success and failure continue to update status using localized strings

### Message-level copy behavior

Required preserved behavior:

- assistant chat messages expose `Copy response`
- assistant chat messages expose `Copy response markdown`
- assistant chat messages expose `Copy table` when rendered HTML contains a table
- markdown transcript extraction preserves current role-label formatting and thinking-block serialization closely enough to avoid changing downstream expectations

## Localization contract

The Svelte rewrite must preserve the existing localization model:

- default strings are available locally before the first host message
- localized strings may arrive in `payload.localized_strings` or `payload.metadata.localized_strings`
- incoming localized strings merge onto existing defaults rather than replacing the object wholesale

At minimum, the rewrite must preserve all keys currently present in the `localizedStrings` initialization in `nvda_ui_host/webui/src/lib/state.svelte.ts` (the empty `Record<string, string>` is seeded by Python `localized_strings`).

## Keyboard and focus contract

The migration must preserve these user interactions:

- `Escape` closes the host window
- `Alt+Shift+T` copies text
- `Alt+Shift+M` copies markdown
- `Alt+Shift+R` clears content
- `Alt+Shift+L` focuses the content region
- `Alt+Shift+I` focuses the chat composer when chat mode is active
- `Alt+Shift+A` triggers file attach when chat mode is active
- `Alt+Shift+S` submits chat when chat mode is active
- `Enter` without `Shift` submits chat from the composer

Required preserved focus behavior:

- focus can be directed to status, content, composer, or first result action
- display commands with actions focus the first result action
- display commands without actions focus content
- chat mode focuses the composer
- attachment removal restores composer focus

Shortcut suppression for text-entry targets must remain equivalent to the current behavior.

## Accessibility contract

The Svelte rewrite must preserve these accessibility properties:

- a live region remains available for assertive announcements if the current shell uses one
- status remains a `role="status"` region with polite announcements
- content remains keyboard-focusable
- shortcut discoverability remains available in the UI
- chat, content, and toolbar controls remain keyboard reachable without pointer-only affordances

The migration may change markup and component structure, but it must not reduce keyboard or screen-reader usability.

## Compatibility rules for the Svelte implementation

The rewrite may change:

- DOM structure
- component boundaries
- CSS organization
- state management strategy
- build tooling

The rewrite must not change, without an explicit protocol update:

- command names
- event names
- event payload shapes already consumed by Python
- attachment object shapes
- copy semantics
- keyboard shortcuts
- the embedded asset file paths expected by the Rust host

## Validation checklist

The Svelte refactor is not complete until all of the following still work:

- the build emits `assets/host.js` and `assets/host.css`
- the Rust host still embeds those assets without source changes, or any source changes are updated in the same patch
- `render_display` renders text, HTML, actions, and thinking content
- `open_chat` opens chat with initial text and optional image
- `chat_set_history`, `chat_append`, and `chat_update` preserve message history behavior
- `chat_stream_begin`, `chat_stream_delta`, `chat_stream_end`, and `chat_stream_abort` preserve streamed-message behavior without full-message resends
- `chat_submitted` includes attachments in the existing shape
- provider, model, and think-mode events still reach Python unchanged
- global and message-level copy actions preserve current output behavior
- all documented shortcuts and focus transitions still work
- invalid inbound envelopes still surface status failures and emit `ui_failed` where they do today

This document is the migration gate for the browser-side refactor.
