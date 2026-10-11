# Original User Request

## 2026-10-02T05:00:45Z

# Teamwork Project Prompt

Perform an evidence-driven architecture audit and produce the comprehensive implementation plan for the current `main` branch of `adil-adysh/NVDA-AI-assistant` moving toward the mandatory target topology and enforcing invariants A1–A30.

Working directory: D:\nvda-addons\NVDA-AI-assistant
Integrity mode: development

## Opening Directives & Team Structure

Assign independent Teamwork agents to:
1. Current architecture/dependency auditor (Audits A, C, G)
2. NVDA boundary/thread-affinity auditor (Audits A, B, Invariants A1–A4, A27)
3. Rust runtime/concurrency auditor (Audit E, Invariants A7–A10, A25–A26)
4. Pure-Python / test architect (Audit D, Invariants A5–A6, A30)
5. Model-management architect (Audit F, Invariants A11–A15)
6. Worker / job / IPC implementation designer (Invariants A16–A24, Slices 2–4, 9–10)
7. Migration / regression reviewer (Review of Slices 0–10, rollback points, risk/blocker checks against A1–A30)

Base work strictly on current HEAD (`ced1cbc` and ancestors). Preserve all recent runtime supervisor, negative visibility, catalog snapshot, and llama catalog improvements.

## Requirements

### R1. Evidence-Driven Architectural Audits (Audits A–G)
Conduct a deep, code-level audit of the current repository state with file paths, line references, and symbol citations:
- **Audit A (Process Topology):** Map every process (NVDA, Python global plugin, `nvda_ui_host.exe`, LiteRT-LM, llama-server, PyO3 extensions, subprocesses) across creation, ownership, transport, health, restart, teardown, and failure isolation. Map against target worker architecture.
- **Audit B (Thread & Executor Map):** Enumerate and classify all production threads, thread pools, locks, condition variables, queues, and background mechanisms into KEEP IN NVDA, MOVE TO PURE PYTHON, MOVE TO WORKER, RUST-OWNED, or REMOVE/CONSOLIDATE. Specifically analyze `plugin/background.py`, `plugin/application.py`, `plugin/local_provider_startup.py`, `ui/task_runner.py`, `ui/adapter.py`, `ui/host_transport.py`, `ui/host_process.py`, and `service/model_cache.py`.
- **Audit C (NVDA Import Contamination):** Trace direct and transitive imports from NVDA (`api`, `textInfos`, `controlTypes`, `globalPluginHandler`, `scriptHandler`, `queueHandler`, `gui`, `wx`, `speech`, `tones`, `logHandler`). Identify the maximum coherent pure-Python domain/service subtree and define clean dependency boundaries.
- **Audit D (Testing Tier Separation):** Analyze root `conftest.py`, `tests/support/bootstrap.py`, sibling NVDA checkout dependency, and define a three-tier test architecture: (1) Pure Python (no NVDA checkout needed), (2) Rust/Worker, (3) NVDA Integration.
- **Audit E (Rust Runtime Supervisor Verification):** Audit `runtime_supervisor` (lifecycle transitions, concurrent `ensure_ready`, generation fencing, process death, adoption, restart, shutdown races, GIL release, startup identity). Identify any existing bugs or gaps before expanding ownership.
- **Audit F (Model Management Consolidation):** Map responsibilities across `model_cache`, `provider_catalog`, `provider_controls`, `provider_readiness`, LiteRT/llama managers, visibility settings, and UI. Design a centralized application `ModelManagementService` coordinating smaller collaborators across modalities (CHAT, VISION, OCR, TRANSCRIPTION, EMBEDDING, TTS).
- **Audit G (`plugin/background.py` Decomposition):** Deconstruct `plugin/background.py` into application orchestration, NVDA presentation, model management, runtime commands, and generic task execution.

### R2. 24-Section Pre-Implementation Deliverable
Synthesize findings into an authoritative, structured pre-implementation artifact containing all 24 required sections:
1. Current process topology
2. Target process topology
3. Current dependency graph
4. Target dependency graph
5. Complete thread/executor map
6. NVDA import map
7. Test-tier redesign
8. Rust supervisor audit & findings
9. LiteRT flow
10. llama flow
11. Current model responsibility map
12. Target model-management decomposition
13. Current background-task map
14. Worker IPC design (versioning, handshake, protocol)
15. Job/session state model
16. Immutable DTO definitions
17. Migration slices (Slices 0–10 detailed plans)
18. Acceptance tests per slice
19. Rollback points
20. Packaging implications (`.nvda-addon`, SCons, wheel packaging)
21. Worker/runtime recovery strategy
22. Accessibility impact
23. Performance/resource limits
24. Risks, blockers, and classified findings (CONFIRMED, LIKELY, DESIGN DETAIL, BLOCKER, UNKNOWN)

### R3. Implementation Plan for Migration Slices (Slices 0–10)
Specify an incremental, independently reversible implementation strategy detailing steps, DTOs, IPC contracts, test plans, and verification gates for:
- Slice 0: Audit + Architecture Contract
- Slice 1: Pure Python Test Boundary
- Slice 2: Job Domain / Protocol
- Slice 3: Worker Process Lifecycle & IPC
- Slice 4: One Real Heavy Operation (e.g. Model Download)
- Slice 5: Model Management Application Boundary
- Slice 6: LiteRT Runtime Ownership Moved to Worker
- Slice 7: llama.cpp Runtime Ownership Moved to Worker
- Slice 8: Removal of Obsolete NVDA-Side Runtime Threading
- Slice 9: OCR Session Foundation (bounded queue, frame dropping)
- Slice 10: Transcription Session Foundation (bounded audio buffer, partial vs finalized transcripts)

## Acceptance Criteria

### Completeness & Evidence
- [ ] All 7 Audits (A–G) are thoroughly completed with concrete code citations (file paths and line numbers) from HEAD (`ced1cbc`).
- [ ] All 24 pre-implementation sections are present and fully fleshed out with actionable technical specifications.
- [ ] Every audit finding and risk is classified using the mandatory tags: CONFIRMED, LIKELY, DESIGN DETAIL, BLOCKER, or UNKNOWN / REQUIRES EXPERIMENT.
- [ ] Any potential blocker to target invariants A1–A30 is backed by concrete code/test evidence, minimal deviation proposal, and intent preservation.

### Architectural Invariant Conformance
- [ ] Target architecture strictly enforces NVDA as a thin accessibility shell with no heavy compute on the NVDA event/main thread (Invariants A1–A4).
- [ ] Clear import boundary separating pure Python application/domain from NVDA adapters is defined with automated import rule enforcement (Invariants A5–A6, A30).
- [ ] Runtime supervisor remains the single authoritative native owner of runtime mechanics; immutable specs and generation fencing are maintained (Invariants A7–A10, A26).
- [ ] Central runtime-neutral model management layer is designed to support multi-modal capabilities (CHAT, VISION, OCR, TRANSCRIPTION, EMBEDDING, TTS) without parallel stacks or silent fallback (Invariants A11–A15).
- [ ] Worker boundary, versioned IPC, immutable DTOs, and session/job models (including bounded queues for continuous OCR/transcription) are fully specified (Invariants A16–A24, A29).

### Verification & Tooling
- [ ] Verification plan includes all three test tiers: Pure Python suite, Rust/Worker suite, and NVDA integration suite.
- [ ] Baseline verification commands (`uv run ruff check .`, `uv run pytest`, `cargo check --manifest-path nvda_ui_host/Cargo.toml`, `cargo test --manifest-path runtime_supervisor/Cargo.toml`) pass without regression.
- [ ] Independent architecture review confirms zero unauthorized deviations from target topology and invariants.


## 2026-10-04T17:22:12Z

# Teamwork Project Prompt

Implement Migration Slice 0 (Rust Supervisor Concurrency Hardening & Contract Cleanup) and Slice 1 (Pure Python Test Boundary Decoupling) for `adil-adysh/NVDA-AI-assistant` following the approved architecture deliverable.

Working directory: D:\nvda-addons\NVDA-AI-assistant
Integrity mode: development

## Requirements

### R1. Slice 0: Rust Runtime Supervisor Concurrency Hardening
Resolve all confirmed concurrency, lifecycle, and containment defects in `runtime_supervisor`:
- **RS-01 (Generation Counter Omission):** Ensure `generation` increments monotonically on every lifecycle state transition, including process crashes, health check timeouts, and unhandled exits, guaranteeing stale health/status updates from prior generations cannot overwrite newer state.
- **RS-02 (Missing Stopping Guard):** Enforce strict guards preventing concurrent `ensure_ready` or startup attempts while the supervisor is in `Stopping` state until the process has fully exited.
- **RS-03 (Socket Collision on Restart):** Ensure `restart()` waits for previous process port release and socket teardown before launching the replacement server process.
- **RS-04 (ensure_ready Livelock):** Add bounded retries with exponential backoff and circuit breaking to prevent infinite tight retry loops during startup failure.
- **RS-06 (Windows Job Object Containment):** Implement Windows Job Object assignment with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` for all spawned child processes to guarantee zero orphaned server processes on crash or exit.
- **RS-10 (Clean Test Shims):** Remove mock/shadow test shims from production PyO3 classes and verify clean production boundaries.
- **Regression Tests:** Add Rust unit/integration tests in `runtime_supervisor/src/tests.rs` verifying each fixed condition.

### R2. Slice 1: Pure Python Test Boundary Decoupling & Import Enforcement
Decouple the testing architecture and establish clean import boundaries:
- **Conftest Sibling Decoupling:** Refactor root `conftest.py` so that pure domain, service, and utility tests can be discovered and executed without requiring the sibling `../nvda` checkout or stubs. Keep NVDA integration tests gated behind `-m nvda_integration`.
- **Logging Decoupling:** Isolate NVDA `logHandler` dependencies in pure domain modules (`core/`, `config/`, `service/`, `providers/`, `use_case/`) by introducing a standard library `logging.getLogger` fallback/facade.
- **Automated Import Boundary Tests:** Add an AST-based architecture test (`tests/test_import_boundaries.py`) verifying that pure Python packages never directly or transitively import forbidden NVDA modules (`api`, `textInfos`, `controlTypes`, `globalPluginHandler`, `scriptHandler`, `queueHandler`, `gui`, `wx`, `speech`, `tones`).

### R3. Zero-Regression Verification Gate
Verify that all existing functionality and test suites continue to pass cleanly:
- `uv run ruff check .` passes with 0 errors.
- `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml` passes with all existing and new tests.
- `cargo check --manifest-path nvda_ui_host/Cargo.toml` passes cleanly.
- `uv run pytest` passes without regression.

## Acceptance Criteria

### Rust Runtime Hardening
- [ ] `runtime_supervisor` tests cover process crash generation fencing (RS-01), stopping state rejection (RS-02), socket reuse/teardown (RS-03), and startup timeout bounds (RS-04).
- [ ] Windows Job Object (`KILL_ON_JOB_CLOSE`) is active on Windows platforms for spawned runtime processes (RS-06).
- [ ] Zero test mock shims remain in production PyO3 module interface (RS-10).
- [ ] `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml` passes 100%.

### Test Architecture & Boundaries
- [ ] `uv run pytest -m "not nvda_integration"` succeeds even if `../nvda` is absent or uninitialized.
- [ ] Automated architecture test `tests/test_import_boundaries.py` is integrated into the pytest suite and passes.
- [ ] Pure Python packages import without requiring NVDA modules.

### Regressions
- [ ] `uv run ruff check .` reports 0 lint or formatting errors.
- [ ] Full existing test suite (`uv run pytest`) passes with 0 failures.


## 2026-10-05T01:52:03Z

# Teamwork Project Prompt

Implement Migration Slice 2 (Job Domain & Versioned Protocol) and Slice 3 (Supervised Worker Process Lifecycle & IPC) for `adil-adysh/NVDA-AI-assistant` following the approved architecture deliverable.

Working directory: D:\nvda-addons\NVDA-AI-assistant
Integrity mode: development

## Requirements

### R1. Slice 2: Job Domain, State Machines, and Versioned IPC Protocol
Implement the pure-Python, NVDA-independent job and protocol contracts:
- **Immutable Job DTOs:** Define frozen dataclasses with slots (`JobId`, `JobSpec`, `JobSnapshot`, `JobProgress`, `JobResult`, `JobFailure`, `JobState`) in `core/job/` or `addon/globalPlugins/AI-assistant/core/job/` satisfying Section 15.1 and Section 16 of the architecture deliverable.
- **Job Finite State Machine:** Implement the monotonic discrete job FSM (`SUBMITTED` → `QUEUED` → `RUNNING` → terminal `COMPLETED`/`FAILED`/`CANCELLED`) with strict state transition validation.
- **Cancellation Contract:** Implement the two-phase cancellation model (cooperative yield token check + supervisor preemption timeout) satisfying Invariant A22.
- **Versioned Wire Protocol:** Define the IPC frame envelope, semantic handshake (`v1.0.0`), command/response framing, and event emission schema over standard JSON/NDJSON streams satisfying Invariants A17, A18, and A20.
- **Client Interfaces:** Provide pure-Python `WorkerClient` and `JobClient` abstract interfaces and mock implementations for isolated testing.

### R2. Slice 3: Supervised Worker Process Lifecycle, Named Pipes, and Failure Isolation
Implement the out-of-process Worker runtime and transport infrastructure:
- **Worker Executable / Entrypoint:** Create the dedicated worker entrypoint (`ai_assistant_worker.py` runnable via python/uv) enclosed in a Windows Job Object (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`) to prevent orphaned processes on NVDA crash.
- **Named Pipe Transport:** Implement bi-directional Windows Named Pipe client/server communication (`\\.\pipe\nvda_ai_worker_cmd` for command/response and `\\.\pipe\nvda_ai_worker_evt` for asynchronous events) with Win32 user-SID DACL permissions.
- **Lifecycle & Supervision:** Implement worker launch, versioned handshake, monotonic 5.0s heartbeat probe, 15.0s liveness timeout, graceful shutdown, and fast (<5ms) broken-pipe detection.
- **Circuit Breaker & Recovery:** Implement exponential backoff worker restart with a circuit breaker tripping after ≥ 3 crashes within 60s (`FAILED_TRIPPED`), halting restart loops and notifying the presenter.
- **End-to-End Trivial Job:** Implement a built-in echo/ping and trivial compute job executed on the worker to prove end-to-end IPC submission, progress streaming, completion, and cancellation.

### R3. Zero-Regression & Failure Isolation Verification Gate
Verify end-to-end system stability and failure containment under adversarial scenarios:
- **Worker Crash Resilience:** Verify that killing the worker process during an active job or idle state does NOT crash, hang, or freeze NVDA, and allows clean reconnection or clear error reporting (Invariant A19).
- **Import Boundaries:** Verify that the worker process and pure job DTOs never import thread-affine NVDA objects (`NVDAObject`, `TextInfo`, `wx`) (Invariants A4, A6).
- **Test Suites:**
  - `uv run ruff check .` passes with 0 errors.
  - `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml` passes 100% (20/20 tests).
  - `cargo check --manifest-path nvda_ui_host/Cargo.toml` passes cleanly.
  - `uv run pytest tests/test_import_boundaries.py` passes.
  - `uv run pytest -m "not nvda_integration"` passes cleanly.
  - New unit and integration tests covering Job DTOs, serialization, named pipe transport, heartbeat timeouts, worker crash recovery, and cancellation pass.

## Acceptance Criteria

### Slice 2: Job Domain & Protocol
- [ ] Immutable frozen DTOs (`JobSpec`, `JobSnapshot`, `JobProgress`, `JobResult`) defined with Draft 2020-12 JSON schema validation.
- [ ] Job state machine strictly enforces monotonic transitions and rejects invalid state regressions.
- [ ] Versioned IPC protocol (`v1.0.0`) handles serialization, deserialization, and error framing with typed error codes.
- [ ] All Slice 2 modules import and pass tests in Tier 1 (pure Python, zero NVDA dependency).

### Slice 3: Worker Process & Lifecycle
- [ ] Worker process runs out-of-process and is assigned to a Win32 Job Object with `KILL_ON_JOB_CLOSE`.
- [ ] Named pipe transport establishes secure bi-directional communication between NVDA and the Worker.
- [ ] Versioned handshake verifies protocol compatibility and rejects incompatible versions.
- [ ] Heartbeat monitor detects unresponsive or dead worker within 15 seconds.
- [ ] Worker crash during active job execution is caught cleanly; NVDA event loop remains sub-50ms responsive; circuit breaker trips after ≥3 rapid crashes.
- [ ] Trivial test job submits, reports progress, and returns terminal result across the named pipe boundary.

### Verification & Tooling
- [ ] `uv run ruff check .` reports 0 lint or formatting errors.
- [ ] `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml` passes (20/20).
- [ ] `uv run pytest` passes without regression across all existing and new tests.

## 2026-10-07T23:43:17Z

# Teamwork Project Prompt

Implement Migration Slice 6 (LiteRT Runtime Ownership Moved to Worker) and Slice 7 (llama.cpp Runtime Ownership Moved to Worker) for `adil-adysh/NVDA-AI-assistant` following the approved architecture deliverable.

Working directory: D:\nvda-addons\NVDA-AI-assistant
Integrity mode: development

## Requirements

### R1. Slice 6: LiteRT-LM Runtime Lifecycle Moved to Worker Process
Relocate native `RuntimeSupervisor("litert-lm")` management from the NVDA process to the supervised Worker process:
- **Worker Host Executor (`worker/executors/litert.py`):**
  - Host and manage the native PyO3 `runtime_supervisor.RuntimeSupervisor("litert-lm", ...)` inside the worker process.
  - Enforce Invariant A7: Exactly one authoritative owner of runtime lifecycle.
  - Enforce Invariant A8: Rust supervisor receives immutable runtime specs.
  - Handle worker commands: `litert_ensure_ready`, `litert_stop`, `litert_restart`, `litert_get_status`, `litert_import_model`.
- **NVDA-Side Routing (`providers/litert_manager.py`):**
  - Route server lifecycle commands through the Worker IPC client (`JobClient` / `NamedPipeWorkerClient`).
  - Retain clean local fallback for standalone unit test environments where worker is mocked or uninitialized.
- **Isolation & Resilience:**
  - Verify that a crash, unhandled exit, or hang of `litert-lm.exe` is trapped by the worker-side Rust supervisor and NEVER crashes, freezes, or hangs the NVDA event thread.

### R2. Slice 7: llama-server Runtime Lifecycle Moved to Worker Process
Relocate native `RuntimeSupervisor("llama-server")` management from the NVDA process to the supervised Worker process:
- **Worker Host Executor (`worker/executors/llama.py`):**
  - Host and manage the native PyO3 `runtime_supervisor.RuntimeSupervisor("llama-server", ...)` inside the worker process.
  - Handle worker commands: `llama_ensure_ready`, `llama_stop`, `llama_restart`, `llama_get_status`, `llama_configure_preset`.
  - Coordinate router preset generation and model switching within the worker process.
- **NVDA-Side Routing (`providers/llama_manager.py`):**
  - Route server lifecycle and readiness checks across Worker IPC.
  - Retain clean local fallback for standalone unit test environments.
  - Remove in-process llama supervisor from `llama_server.py`.
- **Isolation & Resilience:**
  - Verify that a crash or exit of `llama-server.exe` does not affect NVDA process stability.

### R3. Zero-Regression & Multi-Tier Verification Gate
Verify end-to-end system stability across all test tiers:
- **Test Suites:**
  - `uv run ruff check .` passes with 0 errors.
  - `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml` passes 100% (20/20 tests).
  - `cargo check --manifest-path nvda_ui_host/Cargo.toml` passes cleanly.
  - `uv run pytest tests/test_import_boundaries.py` passes (0 forbidden imports).
  - `uv run pytest -m "not nvda_integration"` passes cleanly across all existing and new tests.
  - Unit and integration tests in `tests/worker/` and `tests/providers/` verify out-of-process lifecycle control, status reporting, model import, and crash recovery.

## Acceptance Criteria

### Slice 6: LiteRT Runtime in Worker
- [ ] Worker server hosts `RuntimeSupervisor("litert-lm")` and responds to lifecycle commands over named pipe IPC.
- [ ] Model import via `litert-lm` CLI executes out-of-process in the worker.
- [ ] `LiteRTProvider` queries readiness and initiates server startup over Worker IPC without blocking the NVDA main thread.
- [ ] Process termination of `litert-lm` is contained; monotonic generation counter increments in supervisor state.

### Slice 7: llama.cpp Runtime in Worker
- [ ] Worker server hosts `RuntimeSupervisor("llama-server")` and responds to lifecycle commands over named pipe IPC.
- [ ] Router preset generation and model switching execute out-of-process in the worker.
- [ ] `LlamaProvider` queries status and triggers startup over Worker IPC.
- [ ] Abrupt termination of `llama-server` is contained; NVDA process remains fully responsive.

### Verification & Tooling
- [ ] `uv run ruff check .` reports 0 lint or formatting errors.
- [ ] `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml` passes (20/20).
- [ ] Full existing test suite (`uv run pytest -m "not nvda_integration"`) passes with 0 regressions.

## 2026-10-09T05:56:58Z

# Teamwork Project Prompt

Implement Migration Slice 8 (Removal of Obsolete NVDA-Side Runtime Threading & Shadow Test Shims) for `adil-adysh/NVDA-AI-assistant` following the approved architecture deliverable.

Working directory: D:\nvda-addons\NVDA-AI-assistant
Integrity mode: development

## Requirements

### R1. Slice 8: Deconstruction of `plugin/background.py` & Thread Elimination
Eliminate unmanaged daemon threads, silent fallbacks, and obsolete aliases from `plugin/background.py`:
- **Delete Unmanaged Config Listeners & Daemon Threads:**
  - Remove `_on_litert_server_config_changed` and `_restart_litert_server_worker` (which spawned unmanaged `litert-restart-on-config-change` daemon threads).
  - Remove `_on_llama_server_config_changed` (which spawned unmanaged `llama-shutdown-on-config-change` daemon threads).
  - Unsubscribe `subscribe_litert_server_config_change` and `subscribe_llama_server_config_change` from `plugin/background.py`. Worker process supervises runtime configuration changes authoritatively.
- **Delete Obsolete Test Shim Alias:**
  - Remove `_ensure_litert_server_ready_locked()`.
- **Enforce Invariant A14 (Zero Silent Fallbacks, F-F03):**
  - In `ensure_provider_server_ready()`, eliminate the silent model mutation (`set_model_name(record.model_id)`). If the configured model is unknown/missing, fail closed by raising `LLMProviderError(f"Unknown llama.cpp model: {config.model_name}")` rather than silently mutating user settings.
- **Relocate Domain Functions:**
  - Relocate `_build_import_candidates` to `providers/litert_models.py` (pure hardware inspection).

### R2. Clean Up `plugin/application.py` Shutdown Threads
- **Remove Obsolete Termination Threads:**
  - Delete `LiteRTServerShutdown` and `LlamaServerShutdown` daemon threads from `AIAssistantApplication.terminate()`.
  - Runtime process termination is owned by the Worker process under Windows Job Object (`KILL_ON_JOB_CLOSE`) and `worker_supervisor`.

### R3. Remove Obsolete Production Shadow Test Shims (RS-10)
Purge duplicate Python test shims from production runtime modules (Invariant A7):
- **Delete `_TestShimSupervisor` from `providers/runtime/server.py`:**
  - Remove `_TestShimSupervisor` class and `if _run_litert_cli is not _real_run_litert_cli:` hook from `_get_native()`.
- **Delete `_LlamaTestShimSupervisor` from `providers/runtime/llama_server.py`:**
  - Remove `_LlamaTestShimSupervisor` class and `_process_factory` handling from `_get_native()`.
- **Test Alignment:**
  - Update `tests/integration/test_local_provider_lifecycle.py` and `tests/worker/test_llama_worker_challenge_c2.py` to use explicit mocks without relying on production module test shims.
  - Update `tests/plugin/test_background_shutdown.py` and `tests/plugin/test_background_provider_ready.py` to match the cleaned `background.py` interfaces.

### R4. Zero-Regression Multi-Tier Verification Gate
Verify end-to-end system stability across all test tiers:
- `uv run ruff check .` passes with 0 errors.
- `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml` passes 100% (20/20 tests).
- `cargo check --manifest-path nvda_ui_host/Cargo.toml` passes cleanly.
- `uv run pytest tests/test_import_boundaries.py` passes (0 forbidden imports).
- `uv run pytest -m "not nvda_integration"` passes cleanly across all existing and new tests.
- Verify zero ad-hoc threads spawned during startup/shutdown; zero shadow test shims in production code.

## Acceptance Criteria
- [ ] `plugin/background.py` no longer contains config-change listener threads or `_ensure_litert_server_ready_locked`.
- [ ] Invariant A14 enforced: Zero silent model fallbacks or configuration mutations in `ensure_provider_server_ready()`.
- [ ] `plugin/application.py` no longer spawns `LiteRTServerShutdown` or `LlamaServerShutdown` daemon threads during `terminate()`.
- [ ] `_TestShimSupervisor` and `_LlamaTestShimSupervisor` are completely deleted from `server.py` and `llama_server.py`.
- [ ] All test tiers pass cleanly without regressions (`ruff`, PyO3 `cargo test`, `test_import_boundaries.py`, and full pytest non-NVDA suite).
