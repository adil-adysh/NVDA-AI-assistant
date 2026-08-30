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
- Python setup: `uv sync --locked`
- Python: `uv run ruff check .` and `uv run pytest`
- Built-NVDA tier: `uv run pytest -m nvda_integration`
- Build graph: `uv run scons --dry-run`; full package: `uv run scons`
- Protocol changes: validate Python + Rust + WebUI together

## Test and package invariants
- Keep every repository test under top-level `tests/`; never put tests or
  pytest support inside `addon/`.
- Reuse `tests/support/bootstrap.py` instead of creating per-file import
  loaders or broad fake NVDA module trees.
- Import real NVDA definitions from the sibling revision pinned by
  `nvda-source.toml`. Substitute only process-owned APIs unavailable outside a
  live NVDA process.
- Never weaken the bundle-level test-artifact rejection in
  `site_scons/site_tools/NVDATool/addon.py`; tests and bytecode must not enter
  the `.nvda-addon` archive.
- Full environment and tier instructions are in `docs/development.md`.

## Current runtime rules
- `plugin/factory.py` is the Python composition root.
- `ui/adapter.py` owns host-vs-native fallback and presentation coordination.
- `nvda_ui_host/src/ipc/transport.rs` owns named-pipe transport; `protocol.rs`
  owns the typed v2 contract; `app.rs` owns activation/focus policy.
- Optional PyO3 extensions are `llm_client`, `memory_engine`, and
  `embedding_engine`; each has a Python adapter and a narrower fallback where
  supported.
- NVDA object-model work must be marshalled through the NVDA event queue;
  worker threads must not touch focus/page objects directly.
