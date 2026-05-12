# Architecture

## Overview

The NVDA add-on uses a clean host boundary to separate application intent from UI implementation.

For detailed guidance on supervising the external host executable and managing named-pipe lifecycle, see `docs/ui-host-runtime.md`.

The architecture has three core goals:

- keep use-case and provider logic inside the Python add-on
- keep windowing and WebView integration inside the Rust host
- keep the IPC boundary generic, typed, and versioned

This allows the add-on to evolve its features without coupling business logic to the host process, and allows the host UI to evolve without becoming aware of provider-specific or NVDA-specific rules.

## System split

### Python add-on responsibilities

Python owns:

- use-case orchestration
- prompt and provider selection logic
- conversation state and chat session behavior
- UI intent creation
- configuration, validation, and persistence

The Python side decides what should be shown and what user interactions mean.

### Rust host responsibilities

Rust owns:

- external host process lifecycle
- native window lifecycle
- WebView lifecycle
- UI thread affinity and dispatch
- browser-originated event capture

The Rust side decides how UI is rendered and how browser or window events are captured and forwarded.

### IPC responsibilities

The IPC layer owns only:

- framing
- correlation ids
- acknowledgements and errors
- typed command and event delivery

The IPC boundary must not own use-case behavior, provider behavior, or renderer-specific business rules.

## Layer responsibilities

### Add-on side

- `addon/globalPlugins/AI-assistant/plugin/` is the NVDA-facing entrypoint layer.
- `addon/globalPlugins/AI-assistant/use_case/` owns feature orchestration.
- `addon/globalPlugins/AI-assistant/service/` owns model and chat coordination.
- `addon/globalPlugins/AI-assistant/context/` owns structured context collection.
- `addon/globalPlugins/AI-assistant/ui/host_protocol.py` defines the JSON protocol model.
- `addon/globalPlugins/AI-assistant/ui/host_interface.py` defines the renderer-facing contract.
- `addon/globalPlugins/AI-assistant/ui/adapter.py` chooses between host-backed rendering and native NVDA fallback.
- `addon/globalPlugins/AI-assistant/ui/intent.py` defines host presentation intent values such as `interaction_mode`, `attention_policy`, and `focus_target`.
- `addon/globalPlugins/AI-assistant/ui/host_renderer.py` should remain a thin protocol adapter with reusable payload and event helpers, not a long-term owner of business state.
- `addon/globalPlugins/AI-assistant/ui/host_transport.py` should remain transport-only.
- `addon/globalPlugins/AI-assistant/ui/host_process.py` launches and monitors the external host when needed.
- `addon/globalPlugins/AI-assistant/plugin/presenter.py` maps use-case results into generic UI intents and presentation intent metadata.

### Host side

- `nvda_ui_host/src/protocol.rs` is the single source of truth for envelope parsing and serialization.
- `nvda_ui_host/src/ipc.rs` owns transport and connection management only.
- `nvda_ui_host/src/app.rs` validates commands, emits `ack` or `error`, normalizes work for the UI thread, and maps commands to activation policies.
- `nvda_ui_host/src/window.rs` owns queued UI dispatch, thread affinity, and native foreground/focus/hide behavior.
- `nvda_ui_host/src/webview.rs` applies typed UI commands and translates JavaScript-originated messages into protocol events.

### Web UI side

The Web UI is a TypeScript + Svelte 5 application compiled by Vite into a single `host.js` bundle embedded in the Rust host binary. It follows a clean architecture with clear module boundaries:

**Entrypoint and dispatch:**

- `nvda_ui_host/webui/src/lib/bridge.ts` is the single inbound entrypoint. It validates the protocol envelope (schema/version), merges localized strings, conditionally extracts control state only for `CONTROL_COMMANDS` (`open_chat`, `sync_session`, `render_display`), and dispatches to typed command handlers via a `COMMANDS` table.

**Command handlers (`webui/src/lib/commands/`):**

- Each command (`open-chat`, `chat-history`, `chat-streaming`, `render-display`, `sync-session`, `error-progress-close`) is a pure function receiving `(commandId, payload)`.
- `_shared.ts` provides shared helpers: `applyPresentationState`, `updateChatEnvelope`, `reportUiApplied`, `reportUiFailure`.
- `_events.ts` owns the thin transport wrapper `emitUiEvent` for sending events back to the Rust host.

**Operations (`webui/src/lib/operations/`):**

- `control-ops.ts` owns `updateControlState`, `readPresentationValue`, and `getMetadata` — extracting providers, models, think mode, and presentation state from payload metadata.
- `view-ops.ts` owns view lifecycle: conversation selection state evaluation, reset/clear, and summary deduplication.

**State management:**

- `state.svelte.ts` owns the reactive `appState` object (Svelte 5 `$state`) and simple setters. It does NOT own transcript mutations or control extraction.
- `transcript.svelte.ts` owns the `Transcript` class with a `$state`-backed `_messages` array for inherent reactivity. Components access messages via `appState.chat.transcript.messages` directly.

**Protocol types:**

- `protocol-types.ts` is the single source of truth for WebView-side TypeScript payload types, matching `nvda_ui_host/src/protocol.rs`.

**Supporting modules:**

- `content.ts` — HTML sanitization, content block normalization, text/markdown extraction.
- `actions.ts` — user-initiated actions (copy, submit, provider/model selection, focus).
- `attachments.ts` — file attachment loading and management.
- `shortcuts.ts` — keyboard shortcut registration.

**Components:**

- `webui/src/components/` renders generic content, controls, and chat primitives without provider-specific logic.

## IPC model

### Protocol-first design

The Rust/Python boundary should be treated as a protocol product, not as an internal implementation detail.

The protocol remains stable around a common envelope with:

- `schema`
- `version`
- `id`
- `correlation_id`
- `source`
- `type`

The message families remain:

- `command`
- `ack`
- `error`
- `event`

That contract allows either side to evolve without reopening the transport design for each new feature.

### Logical channels

The preferred long-term shape is two logical channels, even if both are implemented with named pipes:

1. command channel: Python to Rust, request/response only
2. event channel: Rust to Python, asynchronous events only

Why this scales better:

- `render_display`, `open_chat`, `show_error`, and `close_window` are synchronous host commands.
- `ui_applied`, `ui_failed`, `chat_submitted`, `ui_action_invoked`, `provider_selected`, and `window_closed` are asynchronous UI-originated events.
- Separating those flows avoids overloading short-lived request transports with long-lived event semantics.

The current implementation uses a dedicated event pipe. The architectural rule is still the same: command responses and asynchronous UI events stay conceptually separate.

## UI model

### Generic UI intents

The host boundary should carry generic UI intents rather than feature-specific logic.

Examples:

- `render_display`
- `open_chat`
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

The host should render these generically and remain unaware of provider details, prompt logic, or internal NVDA use-case rules.

For chat specifically, `chat_update` is the full-message replacement path, while token streaming should use `chat_stream_begin`, `chat_stream_delta`, and `chat_stream_end` so the add-on does not resend the entire assistant transcript on every partial update.

### Result actions and follow-up flows

Some results should offer follow-up actions rather than only static output.

A common example is:

1. the user asks for an image description
2. the host renders the description result
3. the UI exposes an action such as `Open Chat`
4. selecting that action opens chat preloaded with the same screenshot and optional initial text

This should be modeled as a generic result-action flow rather than as a use-case-specific host customization.

Recommended ownership:

- Python decides which follow-up actions are available.
- Rust and the WebView render those actions generically.
- The WebView emits a typed event such as `ui_action_invoked`.
- Python translates that event into the next application intent, such as `open_chat_with_screenshot`.

This keeps result chaining extensible for future use cases such as:

- `Open Chat` from image description
- `Ask follow-up` from a summary result
- `Retry` from an error result
- `Explain in chat` from a structured extraction result

### Rich UI state

The same architecture supports richer UI capabilities when they are modeled as protocol-backed state rather than host-owned business logic.

Important examples:

- collapsible thinking traces
- provider selection
- model selection

Recommended ownership:

- Python decides whether thinking content is available, whether it may be shown, and which providers or models are valid.
- Rust and the WebView render those capabilities generically.
- The WebView may manage purely local presentation state such as disclosure expand or collapse.
- The WebView emits typed events only when Python must validate, persist, or react to a user change.

Examples:

- Python includes a thinking trace block and marks it collapsed by default.
- The UI renders a disclosure control without embedding model-specific logic.
- Python includes current provider/model state and allowed options.
- The UI emits a selection event when the user changes provider or model.

### Attention and result-view policy

The add-on should describe attention behavior explicitly rather than relying on renderer-side heuristics.

Recommended rules:

- streamed updates render incrementally without changing focus
- streamed updates do not foreground the host window
- a final answer may foreground the host window once if it is backgrounded
- one-shot results such as image description, summary, and structured summary should render as content plus `Open Chat`
- one-shot results should not expose session controls until the user explicitly opens chat

Recommended ownership:

- Python decides `interaction_mode`, `controls_visible`, `attention_policy`, and preferred `focus_target`
- Rust decides how native activation and close behavior are applied
- the WebView applies focus and scroll only as a projection of that protocol-backed intent

Current implementation notes:

- Python produces intent values through `ui/intent.py`
- Rust maps command payloads to activation policy in `nvda_ui_host/src/app.rs`
- the Web UI keeps streaming scroll behavior separate from focus behavior

## Effect on use cases

The EXE and pipe design does not affect every use case equally. The main differences are in reliability, latency, and whether the use case is one-shot or interactive.

### One-shot render use cases

Examples:

- page summary
- structure summary
- image description
- error display
- progress display

These use cases fit the command channel well:

1. Python executes the use case
2. Python sends a typed UI command such as `render_display`
3. Rust renders the result and returns `ack` or `error`

For these flows, the main value of the EXE and pipe design is:

- reliable host startup
- lower latency after the first launch because the EXE is reused
- explicit readiness and health checks
- clean fallback when the host is unavailable

These use cases do not require long-lived asynchronous interaction to be useful.

### Chained result flows

Examples:

- image description followed by `Open Chat`
- summary followed by `Ask follow-up`
- error result followed by `Retry`

These use cases start as one-shot render flows, but they need the UI to expose follow-up actions.

The design impact is:

- the rendered result may include generic `actions`
- the WebView emits `ui_action_invoked`
- Python maps that action to the next application intent

This allows a one-shot use case to transition cleanly into another use case without hardcoding host behavior for individual features.

### Interactive session use cases

Examples:

- open chat
- open chat with page content
- open chat with screenshot

These use cases are not just rendering flows. They become session flows after the first command is rendered.

The design impact is much larger:

- Python must keep ownership of conversation state
- the host UI must emit asynchronous events such as `chat_submitted`
- command delivery alone is not enough for a scalable chat experience

This is why chat is the strongest driver for separating command flow from event flow.

### Rich interactive UI state

Examples:

- provider selection
- model selection
- collapsible thinking traces

These features are supported cleanly when they are modeled as protocol-backed UI state.

The design impact is:

- Python supplies allowed values, current state, and validation rules
- Rust and the WebView render the controls generically
- the UI emits typed events only when Python must validate, persist, or react

This keeps provider logic and model policy out of the host while still allowing rich interaction in the UI.

### Why the more demanding use cases should drive the design

Simple render use cases can work with a minimal command-only transport.

Interactive use cases require more:

- asynchronous event flow
- stable host process reuse
- explicit readiness and recovery behavior
- generic action and state modeling

For that reason, the EXE and pipe architecture should be designed around chat, result actions, and rich UI state rather than only around summary-style rendering.

## Scalability rules

- Add new commands by extending typed payloads, not by changing transport behavior.
- Add new UI events without coupling them to synchronous request lifetimes.
- Keep renderer state out of the transport layer.
- Keep host-specific implementation details out of the presenter and use-case layers.
- Keep provider names, provider availability, and validation logic on the Python side.
- Treat result actions as generic protocol data rather than hardcoded WebView behavior.
- Treat thinking-trace content as structured presentation data, not implicit text conventions.
- Treat the Python and Rust protocol implementations as mirrored contracts and test them accordingly.

## Adding Commands And Events

### Adding a host command

1. document the command in `docs/ui-host-protocol.md`
2. update the Python producer such as the presenter, view model, or adapter
3. update Rust command parsing or dispatch in `nvda_ui_host/src/protocol.rs` and `nvda_ui_host/src/app.rs`
4. update Web UI command handler in `nvda_ui_host/webui/src/lib/commands/` (add a new handler module and register it in `bridge.ts` `COMMANDS` table)
5. update protocol types in `nvda_ui_host/webui/src/lib/protocol-types.ts`
6. validate producer and consumer sides together

### Adding a UI-originated event

1. document the event in `docs/ui-host-protocol.md`
2. emit it from the Web UI
3. keep `nvda_ui_host/src/webview.rs` transport-focused; it should forward the event rather than interpret feature semantics
4. dispatch it in `ui/host_renderer.py`
5. add targeted tests when useful

## Migration direction

The current request/response pipe remains valid for host commands.

The recommended migration path is:

1. keep the existing command path for `command`, `ack`, and `error`
2. introduce a dedicated event path for `event`, or explicit event polling
3. move chat submission and UI-originated callbacks onto that event path
4. keep legacy compatibility inside the protocol layer only

## Packaging

- The external host binary is built from `nvda_ui_host/`.
- The package includes `addon/globalPlugins/AI-assistant/ui_host/nvda_ui_host.exe`.
- `sconstruct` copies the built host executable into the add-on bundle when packaging.

## Design principles

- Protocol payloads are generic and UI-focused.
- Add-on-specific semantics stay inside the add-on layer.
- The host is a renderer backend only; it does not own prompt or use-case logic.
- Native UI fallback remains the default when the host is unavailable.
- WebView2 calls stay on the UI thread; background work reaches the UI only through the bounded window dispatch queue.
- Long-lived asynchronous UI events should not depend on the lifetime of a single command request.
- Provider selection and thinking-trace presentation should be protocol-driven UI state, not business logic embedded in the host.
