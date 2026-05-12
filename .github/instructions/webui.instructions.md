---
applyTo: "nvda_ui_host/webui/src/**/*"
description: "Use when editing the Svelte WebView UI for the external NVDA host, including App.svelte, components, styling, and client-side protocol handling."
---

# Web UI Instructions

The Web UI renders host-backed intents. It should stay generic and protocol-driven.
All source files are TypeScript (`.ts` / `.svelte.ts` / `.svelte` with `lang="ts"`).

## Module Map

```
webui/src/lib/
├── bridge.ts                  # Single inbound entrypoint, protocol validation, dispatch
├── state.svelte.ts            # Reactive appState ($state), simple setters, localization
├── transcript.svelte.ts       # Transcript class with $state-backed _messages array
├── protocol-types.ts          # TypeScript payload types matching protocol.rs
├── content.ts                 # HTML sanitization, content block helpers
├── actions.ts                 # User-initiated actions (copy, submit, focus)
├── attachments.ts             # File attachment loading and management
├── shortcuts.ts               # Keyboard shortcut registration
├── commands/
│   ├── _events.ts             # emitUiEvent transport wrapper
│   ├── _shared.ts             # Presentation metadata, chat envelope, event reporting
│   ├── chat-history.ts        # chat_set_history, chat_append
│   ├── chat-streaming.ts      # chat_stream_begin/delta/end/abort
│   ├── render-display.ts      # render_display
│   ├── open-chat.ts           # open_chat
│   ├── sync-session.ts        # sync_session
│   └── error-progress-close.ts # show_error, update_progress, close_window
└── operations/
    ├── control-ops.ts         # updateControlState, readPresentationValue, getMetadata
    └── view-ops.ts            # Conversation selection, reset, clear
```

## Ownership

- Render typed UI state coming from Python through the host protocol.
- Emit typed UI events for user actions that Python must interpret or persist.
- Keep purely visual state local when Python does not need to know about it.

## Implementation Rules

- Do not introduce provider-specific business logic or use-case branching in Svelte components.
- Favor small components and explicit props over hidden global state.
- Preserve keyboard accessibility and screen-reader friendly labeling because this UI is accessibility-critical.
- Keep styling intentional but lightweight; avoid browser-only behavior that bypasses the host protocol.
- If a UI change requires a new command or event, update the Rust and Python protocol slices in the same change.
- New command handlers go in `webui/src/lib/commands/` and are registered in `bridge.ts` `COMMANDS` table.
- If the command carries control state (providers, models, think mode), add it to `CONTROL_COMMANDS` in `bridge.ts`.
- Use `reportUiApplied(commandId)` from `_shared.ts` instead of emitting `ui_applied` manually.
- Access chat messages via `appState.chat.transcript.messages` directly — there is no `chat.messages` getter.
- Keep focus, scroll, and rendering behavior separate. Streaming updates must not move focus.
- Do not add user-facing label catalogs or fallback UI copy in the Web UI when Python already supplies `localized_strings` for the same surface.
- Web UI fallback text should be limited to transport-safe bootstrapping or defensive rendering, and should not become the primary owner of translator-facing labels.

## Adding a Command

1. Add payload types to `protocol-types.ts`.
2. Create a handler module in `commands/`.
3. Register the handler in `bridge.ts`:
   - Add to `COMMANDS` table.
   - If it carries control state, add to `CONTROL_COMMANDS`.
   - If it should clear status, add to `CLEAR_STATUS_COMMANDS`.
4. Build and validate.

## Validation

- Run `npm --prefix nvda_ui_host run build:webui` after Web UI changes.
- For protocol-affecting changes, validate Rust host compilation (`cargo check --manifest-path nvda_ui_host/Cargo.toml`) and the Python side that produces or consumes the same message.
- Full integration: `scons` to build the complete `.nvda-addon` package.
