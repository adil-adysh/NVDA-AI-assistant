## 2026-10-05T03:27:04Z
You are the Project Orchestrator (Generation 2) for adil-adysh/NVDA-AI-assistant.

Your working directory is:
D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\orchestrator_slice2_3_gen2

Your task is to orchestrate the implementation and verification of Migration Slice 2 (Job Domain & Versioned Protocol) and Slice 3 (Supervised Worker Process Lifecycle & IPC) following the latest user request and the approved architecture deliverable.

Key Artifacts:
- Authoritative User Request: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\ORIGINAL_REQUEST.md (see timestamp 2026-10-05T01:52:03Z)
- Approved Architecture Deliverable: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\architecture_deliverable.md
- Prior Slices Status: Slice 0 and Slice 1 were successfully implemented and verified with VICTORY CONFIRMED (refer to D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\orchestrator_slice0_1_gen2\handoff.md).

Requirements Summary:
1. Slice 2: Job Domain, State Machines, and Versioned IPC Protocol (R1)
   - Immutable Job DTOs: frozen dataclasses with slots (`JobId`, `JobSpec`, `JobSnapshot`, `JobProgress`, `JobResult`, `JobFailure`, `JobState`) in `core/job/` or `addon/globalPlugins/AI-assistant/core/job/` satisfying Sections 15.1 and 16. Draft 2020-12 JSON schema validation.
   - Job FSM with monotonic transitions (SUBMITTED -> QUEUED -> RUNNING -> terminal COMPLETED/FAILED/CANCELLED) with strict state transition validation.
   - Cancellation Contract: two-phase cancellation model (cooperative yield token check + supervisor preemption timeout) satisfying Invariant A22.
   - Versioned Wire Protocol: IPC frame envelope, semantic handshake (v1.0.0), command/response framing, and event emission schema over standard JSON/NDJSON streams satisfying Invariants A17, A18, A20. Typed error codes.
   - Client Interfaces: pure-Python WorkerClient and JobClient abstract interfaces and mock implementations for isolated testing. Tier 1 (zero NVDA dependency).
2. Slice 3: Supervised Worker Process Lifecycle, Named Pipes, and Failure Isolation (R2)
   - Worker executable/entrypoint (`ai_assistant_worker.py` runnable via python/uv) enclosed in Win32 Job Object (KILL_ON_JOB_CLOSE) to prevent orphaned processes on NVDA crash.
   - Named Pipe Transport: bi-directional Windows Named Pipe client/server communication (\\.\pipe\nvda_ai_worker_cmd for command/response and \\.\pipe\nvda_ai_worker_evt for asynchronous events) with Win32 user-SID DACL permissions.
   - Lifecycle & Supervision: worker launch, versioned handshake, monotonic 5.0s heartbeat probe, 15.0s liveness timeout, graceful shutdown, and fast (<5ms) broken-pipe detection.
   - Circuit Breaker & Recovery: exponential backoff worker restart with circuit breaker tripping after >= 3 crashes within 60s (FAILED_TRIPPED), halting restart loops and notifying presenter.
   - End-to-End Trivial Job: built-in echo/ping and trivial compute job executed on the worker to prove end-to-end IPC submission, progress streaming, completion, and cancellation.
3. Zero-Regression & Failure Isolation Verification Gate (R3)
   - Worker crash resilience: killing worker during active job or idle state does NOT crash, hang, or freeze NVDA, allows clean reconnection/error reporting (Invariant A19).
   - Import boundaries: worker process and pure job DTOs never import thread-affine NVDA objects (NVDAObject, TextInfo, wx) (Invariants A4, A6).
   - Test suites:
     - uv run ruff check . (0 errors)
     - uv run cargo test --manifest-path runtime_supervisor/Cargo.toml (20/20)
     - cargo check --manifest-path nvda_ui_host/Cargo.toml
     - uv run pytest tests/test_import_boundaries.py
     - uv run pytest -m "not nvda_integration"
     - New unit and integration tests covering Job DTOs, serialization, named pipe transport, heartbeat timeouts, worker crash recovery, and cancellation pass.
