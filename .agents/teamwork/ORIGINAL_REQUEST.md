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
