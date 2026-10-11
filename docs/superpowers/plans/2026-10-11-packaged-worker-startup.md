# Packaged Worker Startup Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Restore installed local-model operations using a private CPython worker with lazy startup and reusable startup-policy hooks.

**Architecture:** Application composition registers an application-owned lazy supervisor. Status reads never launch it; operations explicitly ensure a connected worker. A separate background startup hook supports worker prelaunch independently of existing server-preload settings.

**Tech Stack:** CPython 3.13.12 embeddable Windows amd64 runtime, locked pywin32, Rust/PyO3 runtime_supervisor, named pipes, uv and SCons.

**Spec:** `docs/superpowers/specs/2026-10-11-packaged-worker-startup-design.md`

## Global Constraints

- No PyInstaller, system Python dependency, pip workflow, NVDA imports in the worker, or packaged bytecode.
- Preserve the existing native lifecycle authority and separate command/event pipes.
- Tests belong only under top-level tests; use shared bootstrap loaders.
- Startup and shutdown IPC run off the NVDA event thread.

## Review Focus

- Concurrent first operations must share one connection attempt and startup failure.
- Termination racing startup must prevent registration of a replacement worker.
- Missing private runtime inside NVDA must fail clearly without launching nvda.exe.
- Extracted bundle must import native dependencies with an unrelated cwd and no external Python.
- Future eager worker launch must reuse the same owner without forcing server launch.

### Task 1: Lazy application owner and startup policy

**Files:** plugin/worker_supervisor.py, plugin/application.py, tests/worker/test_worker_lifecycle.py (paths beneath addon/globalPlugins/AI-assistant for production).

**Interfaces:** `configure_worker_owner()`, `ensure_worker_client()`, `shutdown_worker_owner()`, `LazyWorkerOwner.ensure_client()`, `LazyWorkerOwner.start_in_background()`, `LazyWorkerOwner.close()`.

- [x] Write failing tests for zero eager launches, concurrent deduplication, failed attempt propagation, close during startup, and explicit background prelaunch.
- [x] Run `uv run pytest tests/worker/test_worker_lifecycle.py`; observe failures before implementation.
- [x] Implement one condition-protected owner, per-instance pipe names, safe private-runtime selection, and application composition/termination wiring.
- [x] Run lifecycle and existing supervisor tests; expect pass.

### Task 2: Explicit operation startup

**Files:** providers/runtime/server.py, llama_server.py, download_client.py; tests/worker/test_provider_lazy_start.py.

**Interfaces:** provider `_get_worker_client(*, start: bool = False)` consumes `ensure_worker_client()` for mutations/readiness; status and teardown keep non-starting lookup.

- [x] Write tests proving status does not start a worker, readiness resolves one, and download operations resolve the job adapter.
- [x] Run focused tests; observe failure.
- [x] Route readiness, restart, adoption and model mutations through explicit startup; preserve injected test clients.
- [x] Run focused runtime/provider tests; expect pass.

### Task 3: Reproducible private runtime bundle

**Files:** scripts/build_worker_bundle.py, scripts/build.py, addon/globalPlugins/AI-assistant/worker/__main__.py, sconstruct, tests/build/test_worker_bundle.py and test_worker_bundle_smoke.py.

**Interfaces:** `build_worker_bundle(*, allow_existing: bool = False)` creates worker_host; `validate_bundle(path)` rejects incomplete/forbidden artifacts.

- [x] Write builder tests rejecting nested bytecode and missing required runtime files; source archive excludes tests and site-packages.
- [x] Run tests; observe failure.
- [x] Pin official download checksum, vendor locked pywin32 essentials, build source-only standard-library zip, configure isolated ._pth, copy launcher and native supervisor; integrate build inputs.
- [x] Build bundle and run real handshake/native-status/job smoke from extracted package with unrelated cwd.
- [x] Run ruff, full pytest, Rust supervisor tests, SCons dry-run/full package and recursive archive inspection.

## Execution record

User explicitly requested implementation after approving the non-PyInstaller direction; execute inline without another approval round. Preserve pre-existing workspace changes and leave implementation reviewable without unsolicited commits.

Ruling: use `codex/packaged-worker-startup` in the existing checkout to preserve
the already-tested audit fixes and user-owned coordination files.

Ruling: keep direct download support for standalone development callers before
application composition; configured application operations must enter the lazy
worker and propagate failures. Service-entrypoint tests pin this distinction.

Ruling: existing preload defaults were true and conflicted with the chosen lazy
startup contract. Set new defaults false while retaining explicitly saved values.
Default and setting-roundtrip tests pass.

Review: a fresh reviewer reproduced shutdown/recovery races and first-download
bypass. All three received failing regressions and fixes, and the reviewer
confirmed their resolution (13 focused tests passed independently).

Validation: full SCons release package succeeds; native supervisor tests 20 pass;
bundle and extracted-add-on smoke tests 2 pass with external Python paths disabled.
Recursive package inspection finds no test artifacts or bytecode, and the
extracted bundle passes manifest integrity validation. No live NVDA inference
claim is made.

Final Python verification: `uv run pytest -q` — 819 passed, 2 skipped, 18 deselected, 60 subtests passed. `uv run ruff check .` passes.
