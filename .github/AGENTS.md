# NVDA AI Assistant — Coding Agent Guide

## What this repo is
NVDA screen reader add-on (Python) + external Rust UI host + Svelte 5 WebView.
The host renders generic protocol intents; business logic stays in Python.

## Where things live
- `addon/globalPlugins/AI-assistant/` — Python add-on (plugin, use_case, service, context, providers, ui)
- `nvda_ui_host/src/` — Rust host (protocol, IPC, window, WebView)
- `nvda_ui_host/webui/src/` — Svelte 5 TypeScript WebView UI
- `memory_engine/` — Rust memory extension (PyO3)
- `docs/` — Architecture, protocol, runtime specs

## How features flow
```
Python use_case → presenter → host protocol → IPC → Rust → WebView (render)
User action → WebView event → IPC → Python (interpret)
```

## Key rules
- Providers via `LLMService` + `ProviderProxy`, never directly
- Host commands generic; UI behavior via protocol metadata
- `transcript.svelte.ts` is the single message store (`$state`-backed)
- Access messages via `appState.chat.transcript.messages`
- New commands: handler in `commands/`, registered in `bridge.ts` `COMMANDS`
- No `bumpChatRenderVersion` — auto-derived from `transcript.count`
- Full instructions: `.github/copilot-instructions.md`
- Layer-specific: `.github/instructions/*.md` (auto-loaded by `applyTo`)

## Build & validate
- Web UI: `npm --prefix nvda_ui_host run build:webui`
- Rust: `cargo check --manifest-path nvda_ui_host/Cargo.toml`
- Python: `python -m ruff check .`
- Full: `scons`
- Protocol changes: validate Python + Rust + WebUI together
