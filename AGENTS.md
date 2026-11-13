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
  authoritatively by the native Rust `runtime_supervisor` PyO3 extension inside
  the private worker; Python
  owns high-level model catalog, import policies, and application settings.
- The private CPython worker is application-owned and lazy by default. Status
  reads must remain passive; worker preparation and server startup are distinct
  policies. Shutdown must fence launches and recovery before teardown.
- Runtime operations, native embeddings and conversation repository IO use worker
  jobs. The command pipe carries bounded acknowledgements, health, cancellation
  and shutdown; progress and terminal results use the event pipe. Do not wait for
  long operations while holding the command lock or on the command listener.
- Worker execution has separate serialized lanes for each runtime, embeddings and
  persistence, plus reserved status/stop capacity. Validate job generations and
  preserve terminal events under progress congestion. Native blocking work must
  release the GIL so control threads remain responsive.
- NVDA event-thread status reads use cached snapshots with asynchronous refresh.
  An authoritative `status(refresh=True)` read is a blocking operation and must
  run off the NVDA event thread. Chat presentation IO is serialized off-thread.
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


## Model registration and preset ownership

- Drive model-manager controls from explicit model actions when supplied, keeping
  registration, file ownership, file availability and runtime state independent.
- User-supplied llama.cpp presets are one-time migration input. Keep originals
  unchanged; reject unsupported options with a section/key summary. `models.json`
  owns model settings after migration. Generate `runtime-models.ini` solely from
  records using `LlamaPresetCodec`; never merge stale output or reread external
  presets during refresh. Keep option validation in `core/llama_options.py` and
  inspect installed runtime capabilities in the worker. Catalog discovery must
  never silently register a model.
- Remove registrations by exact ID, preserve user model files/shared upstream cache,
  and verify runtime status before stopping an owned router. Clear selections using
  compare-and-set. Worker cache deletion must independently verify the managed root
  and an explicit ownership record; never infer ownership from a filename.

- llama.cpp configurations, downloaded assets and server entries use the shared
  `providers/llama_catalog.py` policy. Discover/verify assets in the worker; preserve
  exact IDs and source ownership. Cache reuse must not copy/download weights or
  start inference servers. Do not use server-reported paths as local ownership proof.
- Preset replacement requires a digest-bound preview. UI reads do not trigger
  mutation refresh/focus behavior; closed/stale callbacks never reopen dialogs.
- llama model lifecycle operations are application-owned in `service/llama_operations.py`.
  Closing the manager/Tasks detaches observers; Stop cancels one operation. Fence
  new starts before worker shutdown. Disposable UI scans may cancel on dismissal.
- Companion roles are explicit (vision, draft, MTP). Resolve/download in the worker
  only for Load/first inference; reuse unchanged verified immutable cache files
  offline. Validate installed speculative modes, preserve legacy overrides, and
  invalidate compatibility after changing sources/settings. Block shared-file
  deletion at both manager and worker boundaries, including companion references.
