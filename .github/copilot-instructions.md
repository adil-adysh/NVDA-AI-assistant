# GitHub Copilot Instructions — NVDA AI Assistant

Layered NVDA add-on + external Rust UI host + Svelte 5 WebView.

## System Model

```
NVDA → GlobalPlugin → UseCaseEngine → ContextPipeline → LLMService → Provider
                    → Result → Presenter → NVDA UI

Python add-on → host protocol → named-pipe IPC → Rust host → WebView / Svelte UI
                                                              → UI event → Python
```

## Layer Rules

Layer-specific rules live in `.github/instructions/` (loaded via `applyTo` patterns):
- `python-addon.instructions.md` — applies when editing `addon/.../**.py`
- `rust-host.instructions.md` — applies when editing `nvda_ui_host/src/**/*.rs`
- `webui.instructions.md` — applies when editing `nvda_ui_host/webui/src/**/*`

### Cross-cutting rules (all layers)

- Python owns: use-case orchestration, prompt logic, provider selection, conversation state, UI intent.
- Rust owns: host process lifecycle, native window, WebView lifecycle, UI thread dispatch.
- WebView owns: rendering generic host intents, emitting typed UI events.
- IPC owns: framing, correlation IDs, acks/errors, typed command/event delivery.
- Access providers through `LLMService` + `ProviderProxy`, never directly.
- Keep host commands generic and protocol-backed.
- Express UI behavior through protocol metadata (`interaction_mode`, `controls_visible`, `attention_policy`, `focus_target`).
- Streaming updates must not change focus. Final answers may request foreground.
- One-shot results use `result_action_only` views with generic result actions.

## Required Patterns

- New features should usually be implemented as a `UseCase` and registered in `use_case/registry.py`.
- Use `ContextPipeline` with `ExtractionIntent` (carrying typed `ContentRequest` objects like `PageTextRequest`, `ForegroundImageRequest`) instead of hand-building prompt context in a feature.
- Access providers through `LLMService` and `ProviderProxy`, never directly from `use_case/` or `ui/`.
- Register tool behavior in the tool registry/executor path instead of invoking tools directly from a feature.
- Keep host commands generic and protocol-backed. If Python and Rust both change, update the protocol contract deliberately.
- Express host-backed UI behavior through protocol-backed presentation metadata such as `interaction_mode`, `controls_visible`, `attention_policy`, and `focus_target`.
- Streaming updates must not change focus. Final answers may request `foreground_if_background` when Python wants to surface the completed answer.
- One-shot results such as image description, summary, and structured summary should be modeled as `result_action_only` views with generic result actions.

## Adding Commands And Events

When adding a host command:

1. document it in `docs/ui-host-protocol.md`
2. update the Python producer such as `presenter.py`, `view_models.py`, or `adapter.py`
3. update Rust parsing and dispatch in `nvda_ui_host/src/protocol.rs` and `nvda_ui_host/src/app.rs`
4. update Web UI command handler in `nvda_ui_host/webui/src/lib/commands/` (add a new handler module and register it in `bridge.ts` `COMMANDS` table)
5. update protocol types in `nvda_ui_host/webui/src/lib/protocol-types.ts`
6. validate both the producer and consumer sides

When adding a UI-originated event:

1. document it in `docs/ui-host-protocol.md`
2. emit it from the Web UI
3. keep `webview.rs` transport-focused; it should forward rather than interpret feature semantics
4. dispatch it in `ui/host_renderer.py` and route it to the owning Python layer
5. add targeted tests where useful

## Hard Constraints

- Do not call providers from `use_case/` or UI code.
- Do not access NVDA APIs outside the plugin/context layers unless an existing pattern already permits it.
- Do not block the NVDA main thread.
- Do not hardcode provider names or provider-specific branching outside provider/config layers.
- Do not mix UI rendering concerns with business logic.
- Do not introduce parallel abstractions when an existing `UseCase`, `ContextPipeline`, presenter, or host protocol type already fits.
- Do not implement new result behavior by branching on use-case id in the Web UI when presentation intent metadata can express it.
- Do not add new state properties directly on `appState.chat` for message data — use `appState.chat.transcript` (the `Transcript` instance).
- Do not import `bumpChatRenderVersion` — it no longer exists. Auto-scroll derives from `appState.chat.transcript.count`.
- Do not call `updateControlState` from individual command handlers — it is called centrally in `bridge.ts` only for `CONTROL_COMMANDS`.
- Do not emit `ui_applied` manually from command handlers — use `reportUiApplied(commandId)` from `_shared.ts`.

## Validation Defaults

Match validation to the slice you changed:

- Python add-on changes: `python -m ruff check .` and targeted type or runtime checks when available.
- Rust host changes: `cargo check --manifest-path nvda_ui_host/Cargo.toml`.
- Web UI changes: `npm --prefix nvda_ui_host run build:webui` (TypeScript + Vite build).
- Cross-boundary protocol changes: validate both Python and Rust/Web UI sides.

## Supporting Docs

- `docs/architecture.md` describes the Python/Rust/WebView split and IPC ownership.
- `docs/ui-host-runtime.md` covers host supervision and pipe lifecycle.
- `docs/ui-host-protocol.md` covers protocol expectations.
- Additional file-scoped guidance lives in `.github/instructions/`.
- Task-specific workflows live in `.github/skills/` and `.github/agents/`.

---

## 19. Project Constraints

- NVDA add-on (accessibility-critical)
- Must remain responsive
- Supports:
  - page summarization
  - image description
  - contextual chat

Providers:
- Ollama (preferred, local-first)
- Gemini (optional fallback)

---

## 20. If Uncertain

- Do NOT guess architecture
- Ask for clarification
- Or follow existing similar implementation
