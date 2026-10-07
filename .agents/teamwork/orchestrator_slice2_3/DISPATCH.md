# Incoming Dispatch

## 2026-10-05T01:54:00Z

You are the Project Orchestrator for adil-adysh/NVDA-AI-assistant.

Your working directory is:
D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\orchestrator_slice2_3

Your task is to orchestrate the implementation of Migration Slice 2 (Job Domain & Versioned Protocol) and Slice 3 (Supervised Worker Process Lifecycle & IPC) following the latest user request and the approved architecture deliverable.

Key Artifacts:
- Authoritative User Request: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\ORIGINAL_REQUEST.md (see timestamp 2026-10-05T01:52:03Z)
- Approved Architecture Deliverable: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\architecture_deliverable.md
- Prior Slices Status: Slice 0 and Slice 1 were successfully implemented and verified with VICTORY CONFIRMED (refer to D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\orchestrator_slice0_1_gen2\handoff.md).

Requirements Summary:
1. Slice 2: Job Domain, State Machines, and Versioned IPC Protocol (R1)
   - Immutable Job DTOs (frozen dataclasses with slots: JobId, JobSpec, JobSnapshot, JobProgress, JobResult, JobFailure, JobState in core/job/ or addon/globalPlugins/AI-assistant/core/job/ satisfying Sections 15.1 and 16).
   - Job FSM with monotonic transitions (SUBMITTED -> QUEUED -> RUNNING -> terminal COMPLETED/FAILED/CANCELLED).
   - Cancellation Contract (two-phase cancellation model satisfying Invariant A22).
   - Versioned Wire Protocol (v1.0.0 semantic handshake, JSON/NDJSON streams satisfying Invariants A17, A18, A20).
   - Pure-Python Client Interfaces (WorkerClient and JobClient abstract interfaces and mocks).
2. Slice 3: Supervised Worker Process Lifecycle, Named Pipes, and Failure Isolation (R2)
   - Worker executable/entrypoint (ai_assistant_worker.py runnable via python/uv) enclosed in Win32 Job Object (KILL_ON_JOB_CLOSE).
   - Named Pipe Transport (\\.\pipe\nvda_ai_worker_cmd and \\.\pipe\nvda_ai_worker_evt) with Win32 user-SID DACL permissions.
   - Lifecycle & Supervision (worker launch, handshake, 5.0s heartbeat probe, 15.0s liveness timeout, graceful shutdown, <5ms broken-pipe detection).
   - Circuit Breaker & Recovery (exponential backoff restart tripping after >= 3 crashes within 60s -> FAILED_TRIPPED).
   - End-to-End Trivial Job (echo/ping and compute job over worker IPC).
3. Zero-Regression & Failure Isolation Gate (R3)
   - uv run ruff check . (0 errors)
   - uv run cargo test --manifest-path runtime_supervisor/Cargo.toml (20/20)
   - cargo check --manifest-path nvda_ui_host/Cargo.toml
   - uv run pytest tests/test_import_boundaries.py
   - uv run pytest -m "not nvda_integration"
   - New unit and integration tests covering Job DTOs, serialization, named pipe transport, heartbeat timeouts, worker crash recovery, and cancellation.

Operating Rules:
- You are a pure orchestrator: do NOT write production code yourself. Dispatch tasks to specialists (explorers, workers, reviewers, challengers, auditors).
- Regularly update progress.md and BRIEFING.md in your working directory.
- When all requirements and verification gates pass, report completion back to the Sentinel.
