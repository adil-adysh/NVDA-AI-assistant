# Operation ownership implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task.

**Goal:** Prevent stale UI delivery and conflicting runtime mutations using explicit owners.
**Architecture:** Pure state and outcome rules are consumed by Python application services.
NVDA/UI and worker/file adapters implement effects, wired at composition roots. Extend
existing model operations rather than add a parallel lifecycle framework.
**Tech Stack:** Python 3.13, existing worker IPC and native Rust supervisor.
**Spec:** ../specs/2026-11-21-operation-ownership.md

## Global constraints
Preserve repository AGENTS.md architecture/threading/protocol/preset rules. Tests only
under tests/. Keep existing uncommitted gesture compatibility fix. Do not push or merge.

## Review focus
Stale callbacks after dismissal/reactivation; multiple choice pages; load/removal admission;
queued cancellation and normal return after cancel; shutdown and observer detachment.

## Task 1: Command sessions
- [x] Add failing state-machine and application-delivery regression tests.
- [x] Extract pure session state/choice identities; adapt layer_mode and application selectors.
- [x] Fence all lookup deliveries and shutdown, paginate choices and restore bindings.
- [x] Run focused plugin tests and review.

## Task 2: Model lifecycle coordination
- [x] Add barrier-based removal/load/stop/adoption/shutdown tests.
- [x] Extend existing service/llama_operations.py coordination and lifecycle admission.
- [x] Coordinate manager mutations and worker/native fencing without blocking control IPC.
- [x] Preserve durable operations on view dismissal and verify producer/consumer contracts.
- [x] Run focused tests and review.

## Task 3: Outcomes and diagnostics
- [x] Add failing tests for cancellation followed by return and detached view delivery.
- [x] Introduce shared terminal outcome rules and injectable diagnostics port/adapter.
- [x] Wire diagnostics at composition root and reuse outcomes for model-operation presentation.
- [x] Run focused tests and review.

## Task 4: Integration
- [x] Update architecture documentation and verify full suite/lint/build graph.
- [x] Review the whole change, fix verified issues, and report remaining limitations.

## Execution ledger
Ruling: use a dedicated branch in the current configured checkout, preserving existing
gesture edits and NVDA sibling/toolchain discovery rather than duplicating the environment.
Baseline: previous full suite 1416 passed, 8 skipped, 19 deselected; lint clean.

Task 1 reviewed clean: actual NVDA script dispatch, session fencing and pagination.
Task 3 reviewed clean: shared outcomes, detached delivery, null ports and factory adapters.
Focused integration: 165 passed and 18 subtests passed. Initial full run during active
fixture edits failed only the then-incomplete selector UI boundary; fixed and focused green.

Task 2 validation: 375 focused Python tests passed, 5 skipped, 58 subtests;
29 Rust tests passed with pinned PYO3_PYTHON; direct compiled native fence smoke passed.
UI persistence follow-up: Save/Duplicate now capture values and execute off-thread;
view closure detaches their task delivery. Dialog/source regression suite: 31 passed.

Final review found and resolved one lifecycle issue: Starting/Restarting owned
children must be stopped even when native is_running is false. Two deterministic
native spawn/health barriers verify drain, late-child termination and subsequent
startup. Scoped re-review clean; final Rust suite 31 passed and Python lifecycle
regressions 93 passed. Exact catalog snapshots are revalidated after admission.

Packaged validation: restored the missing CI-referenced test_worker_bundle_smoke.py;
isolated shipped interpreter/worker/core exercises handshake, native status, startup
fence jobs, stale token rejection and health across watchdog ticks. Required packaged
gate 8 passed; native shutdown smoke preserved external servers for both runtimes.
Web UI 57 passed. Full package built and inspected: 1046 entries, new modules match
source and no tests or bytecode. Final full Python run: 1458 passed, 8 skipped, 19 deselected, 83 subtests passed (82.07s).

Whole-change review and scoped fix re-review are clean. Full package rebuild,
lint and diff checks passed. Changes remain uncommitted on codex/operation-ownership-refactor;
no merge, push or running NVDA add-on replacement was performed for this refactor.
