---
name: route-change
description: "**UTILITY SKILL** — Decide where a change belongs in the NVDA AI Assistant. USE FOR: determining which layer owns a feature; scoping cross-boundary protocol work; identifying owning abstraction before editing. DO NOT USE FOR: implementing features; writing code; general coding questions. INVOKES: file reads (docs/architecture.md), grep. FOR SINGLE OPERATIONS: skip this skill and edit directly."
---

# Route Change

Use when unclear which layer should own the behavior.

## Workflow

1. Classify: NVDA plugin, use case, context, service, provider, Python UI adapter, Rust host, Web UI, or docs.
2. Check `docs/architecture.md` for cross-boundary changes.
3. Name the owning abstraction first (e.g., `UseCase`, presenter, collector, protocol model, host command handler, Svelte component).
4. Spanning Python + Rust/Web UI → treat as protocol-backed change.
5. Host-backed UI → decide: Python presentation intent, Rust window behavior, or Web UI presentation state.
6. Recommend cheapest validation that can falsify.

## Layer Map

- Gesture, NVDA lifecycle, scheduling → `plugin/`
- Feature intent, orchestration → `use_case/`
- Data gathering → `context/` (use `ExtractionIntent` + `ContentRequest` via `ContextPipeline`)
- Streaming, chat, providers, tools → `service/`
- Provider adapters → `providers/`
- Windowing, WebView, pipes → `nvda_ui_host/src/`
- Browser rendering → `nvda_ui_host/webui/src/`
- New commands: Python intent → `host_protocol.py` → `protocol.rs` → `bridge.ts`
- New UI events: Web UI → `webview.rs` → event pipe → `host_renderer.py`

## Expected Output

owning layer, likely files, constraints to preserve, validation check
