# NVDA AI Assistant — Repository Agent Guide

This repository contains an NVDA Python global add-on, optional Rust/PyO3
extensions, a Rust/WebView2 UI host, and a Svelte 5 Web UI.

## Architecture

- Python owns gestures, lifecycle, use cases, context, prompts, providers,
  chat, tools, persistence, and presentation intent.
- `nvda_ui_host.exe` owns the native window, WebView2, UI-thread dispatch, and
  named-pipe transport.
- Svelte renders generic protocol-backed state and emits typed UI events.
- `ui/adapter.py` selects the host-backed surface or native NVDA fallback.
- Read `docs/architecture.md` and `docs/architecture-current.md` before
  cross-layer changes.

## Boundaries

- Route feature behavior through `UseCaseEngine`, `ContextPipeline`,
  `LLMService`, `ProviderProxy`, and the presenter where applicable.
- Do not call providers directly from `use_case/` or UI code.
- Do not put prompt, provider, use-case, or NVDA business logic in Rust/Svelte.
- Keep command and asynchronous event pipes conceptually separate.
- Wrap user-facing Python strings in gettext `_()` and translate literal
  templates before `.format(...)`. Keep protocol IDs and diagnostic-only logs
  stable. Runtime modules may use `core/translation.py` without importing NVDA.
- NVDA object-model access is thread-affine: resolve page, focus, selection,
  and image snapshots on the NVDA event thread via `ui/nvda_ui.py` wrappers;
  keep network, model, download, and persistence work off that thread.
- Protocol changes must keep Python `ui/host_protocol.py`, Rust
  `nvda_ui_host/src/protocol.rs`, and Web UI `protocol-types.ts` aligned.
- Managed local-runtime lifecycle (`LiteRT-LM` and `llama-server`) is owned
  authoritatively by the native Rust `runtime_supervisor` PyO3 extension; Python
  owns high-level model catalog, import policies, and application settings.
- The private CPython worker is application-owned and lazy by default. Status
  reads must remain passive; worker preparation and server startup are distinct
  policies. Shutdown must fence launches and recovery before teardown.
- Escape/Close hides the native window and WebView controller without cancelling
  requests. Completed responses may activate the host; background progress must
  not take focus. Stop cancels requests and preserves stopped partial chat answers.
- One-shot output preferences apply only to successful one-shot results. Retained
  results and their action payloads must survive dismissal and speech cancellation.

## Validation

- Install/update Python tooling with `uv sync --locked`; do not maintain a
  parallel pip requirements workflow.
- Python: `uv run ruff check .` and `uv run pytest` (or focused pytest nodes).
- Tests live only under top-level `tests/`. Never add `test_*.py`, a `tests/`
  directory, pytest configuration, fixtures, or bytecode beneath `addon/`.
- Use the shared loaders in `tests/support/bootstrap.py`. Tests should import
  real NVDA API definitions from the pinned sibling checkout; replace only
  process-owned surfaces that cannot exist outside a running NVDA process.
- `nvda-source.toml` pins the sibling `../nvda` revision. The normal suite
  needs its source tree; `uv run pytest -m nvda_integration` additionally needs
  a recursively initialized and built NVDA checkout.
- Packaging must preserve the defense-in-depth exclusion in
  `site_scons/site_tools/NVDATool/addon.py`. An `.nvda-addon` must never contain
  tests, pytest files, fixtures, or Python bytecode.
- Rust host: `cargo check --manifest-path nvda_ui_host/Cargo.toml`.
- Rust supervisor: `cargo test --manifest-path runtime_supervisor/Cargo.toml`.
  Set `PYO3_PYTHON` to the locked `.venv/Scripts/python.exe` on Windows; do not
  silently compile against a newer unsupported system Python.
- Web UI: `npm --prefix nvda_ui_host run build:webui`.
- Web UI regressions: `npm --prefix nvda_ui_host run test:webui`.
- Before release, build the package and run worker smoke tests with
  `NVDA_AI_REQUIRE_PACKAGED_TESTS=1`. Run the desktop WebView2 dismissal test
  documented in `docs/development.md` when changing native focus or hiding.
- Cross-boundary changes: validate the producer and consumer sides together.
- Build graph: `uv run scons --dry-run`; full package: `uv run scons`.
- See `docs/development.md` for checkout setup, test tiers, and packaging checks.
