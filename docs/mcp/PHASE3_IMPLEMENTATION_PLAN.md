# Phase 3 Implementation Plan: Final Tool Correctness and Rust MCP Feasibility

**Goal:** Prove the hardened Python tool boundary remains safe under binding reuse, then build and test an isolated feasibility prototype using the official `rmcp` client for stdio and Streamable HTTP.

**Architecture:** Preserve the existing Python authorization, schema, execution and persistence layers. Add a binding-incarnation check at live dispatch; keep MCP in a standalone Rust prototype process, with a versioned JSON-line contract suitable for a future private-worker adapter but not shipped in the add-on. Prototype transports use `rmcp`; tests use deterministic local MCP servers.

**Tech Stack:** Python 3.13, pytest, Rust stable/MSVC, Tokio, official `rmcp` client, serde/serde_json, local Windows process APIs.

**Spec:** `docs/mcp/PHASE3_IMPLEMENTATION_PLAN.md` implements the pasted Phase 3 assignment (Tasks 00–08).

## Global Constraints

- Preserve the existing Python tool loop and deny-by-default host authorization.
- Do not implement MCP protocol framing manually; pin the published official `rmcp` SDK and required transport features.
- Do not add the Python MCP SDK or package this prototype into the add-on.
- Do not modify the sibling NVDA MCP Bridge unless a reproducible compatibility defect requires it.
- The original assignment prohibited pushing; the user later explicitly authorized merging and pushing the completed changes to `main`.
- Keep tests under top-level `tests/`; keep prototype code under `mcp_client_prototype/`.
- Cancellation and timeout do not imply rollback; mutating calls are never retried automatically.

## Review Focus

- Reused stable `tool_id` after revocation: old handler is rejected while current handler runs.
- Ordinary catalog refresh during an already-authorized operation: original handler completes without redirection.
- Remote HTTP trust and local executable trust: distinct validation and credential/logging paths.
- MCP schemas/results with nulls, large payloads, duplicate tool names and tool-level errors: preserve meaning or fail with bounded protocol errors.
- Parent/manager/child crash and grandchildren: lifecycle containment is verified on Windows and stated narrowly where the environment cannot prove it.

## Task Plan and Evidence

### Task 00 — Audit and baseline

- [x] Read repository guide, architecture docs, hardening plan, tool registry/executor/provider/policy, worker, supervisor and UI-host build configuration.
- [x] Confirm HEAD `1b74679` and identify preexisting worktree entries (`.superpowers/` plus generated assets); preserve them.
- [x] Inspect sibling `D:\nvda-addons\nvda-mcp` at `907772a`; its `rust_mcp_bridge` is an official `rmcp 3.9.0` server using stdio, not a client. No bridge compatibility change is presently demonstrated.
- [x] Verify official SDK docs: client child-process and Streamable HTTP transports, client lifecycle modes and protocol negotiation.
- [x] Re-run prior hardening suite: 1,267 passed, 2 skipped, 40 deselected, 60 subtests; focused regression suite after Phase 3: 87 passed (one run before manager shutdown fix had 1 expected contract failure, subsequently fixed).

### Task 01 — Binding incarnation (P0)

Files: `addon/globalPlugins/AI-assistant/tools/registry.py`; `tests/tools/test_registry.py` and `tests/tools/test_executor.py`.

- [x] Add deterministic unregister/re-register same-ID regression; old snapshot is rejected and current snapshot calls the replacement handler.
- [x] Cover disable/enable, provider disconnect/reconnect, ordinary refresh in-flight, atomic replacement and execution/mutation races.
- [x] Implement incarnation/revocation fencing. Ordinary already-dispatched calls remain bound to their original handler.
- [x] Run focused and complete Python suites, Ruff pending final run.

### Task 02 — Hardening verification

Files: `tests/tools/`; evidence updates in this plan.

- [x] Differential-check supported schema assertions against the Draft 2020-12 reference, including `$ref` siblings, conditionals, dependencies, property names, contains cardinality, numeric semantics, valid contains annotations, and unsupported assertions; inspect actual Bridge schemas during its discovery test.
- [x] Exercise byte/envelope, JSON/media, structured round-trip, normalization, admission, uncertainty, live authorization and registry API boundaries.
- [x] Findings and limitations recorded in `docs/tool-system/HARDENING_PLAN.md`.

### Task 03 — Standalone official `rmcp` prototype

Files: `mcp_client_prototype/Cargo.toml`, `Cargo.lock`, `src/`, `tests/`, and deterministic stdio/HTTP fixtures.

- [x] Pin released official `rmcp 3.9.0` and minimal client child-process/Streamable HTTP features; negotiate 2026-07-28 preferred with 2025-11-25 fallback.
- [x] Implement discovery, call, list-change events, IDs, cancellation, timeout, shutdown, structured results and protocol-vs-tool errors with SDK APIs.
- [x] Test unrelated stdio and Streamable HTTP servers, plus the real sibling Bridge stdio binary with a token-checked HTTP fixture.
- [x] Formatting, Clippy (`-D warnings`), Rust tests and release binary size (4,453,888 bytes) recorded.

### Task 04 — Process architecture decision

Files: `docs/mcp/PHASE3_IMPLEMENTATION_PLAN.md`, prototype measurement scripts/results.

- [x] Compared measured release size and qualitative startup/memory, crash isolation, lifecycle coupling, IPC, ownership, deployment and test complexity. PyO3 idle/active memory and startup were not benchmarked because no integrated build exists.
- [x] Recommend standalone manager for clearer process isolation and separate lifecycle; evidence does not support placing it in the UI host or coupling it into the worker. This is a prototype direction, not a production integration decision.

### Task 05 — Versioned Python-manager contract

Files: `docs/mcp/IPC_CONTRACT.md`, prototype protocol types/tests, Python contract harness.

- [x] Specify operations, IDs/generations, exact identity, complete schemas/results and classified uncertainty in `IPC_CONTRACT.md`.
- [x] Define size/history limits, out-of-order replies, reconnect/crash/version handling and auth/secrets policy.
- [x] Map adaptation to worker pipes; keep full production integration deferred.

### Task 06 — Windows lifecycle and security

Files: prototype process supervisor and deterministic lifecycle tests; `docs/mcp/SECURITY.md`.

- [x] Own child processes through `rmcp` child transport and Windows Job Object/KillOnDrop; stderr is drained. Direct child shutdown is tested; malicious-grandchild termination is documented as an outstanding test.
- [x] Test stalled tool cancellation, shutdown, uncertain/no-retry semantics, frame cap, and credential handling through Bridge fixture.
- [x] Separate local executable and HTTPS/loopback-only HTTP policies in `SECURITY.md`.

### Task 07 — Cross-language contract tests

Files: `tests/tools/` fake-client contract coverage, Python harness, prototype integration tests.

- [x] Cover two servers/duplicate names, schema discovery, structured/tool errors, cancellation/uncertainty, generation events, manager contract, and Python binding-incarnation/revocation behavior without model inference.
- [ ] Production Python authorization adapter, worker crash/restart, and external permission-denial wiring remain deferred until integration.

### Task 08 — Final validation/review

- [ ] Run locked Python sync, Ruff, full pytest, Rust fmt/Clippy/tests, supervisor tests, UI host checks, SCons graph and package build.
- [ ] Verify prototype files/binaries are excluded from `.nvda-addon`.
- [ ] Independently review diff; finish required findings/status/evidence and record limitations.
- [ ] Make focused commits on `main` and push per the user's explicit authorization.

## Initial Evidence

- Current repository HEAD: `1b74679e7e6f51e5304d10d3860c974dbe807a39`.
- Prior hardening commit tests: 1,260 passed, 2 skipped, 40 deselected; focused tools 103 passed (from the hardening record; Task 00 baseline will be rerun in this phase).
- Official SDK current docs list `TokioChildProcess` and `StreamableHttpClientTransport`; current lifecycle API negotiates protocol versions. The sibling server pins `rmcp 3.9.0`, but the client prototype will pin the selected compatible release independently.

## Remaining Risks

- The sibling Bridge stdio server and unrelated Streamable HTTP server are verified. Its bridge-to-NVDA HTTP is distinct from MCP Streamable HTTP and is simulated in the sibling compatibility fixture.
- No production Python-to-manager integration, actual NVDA event-thread flow, malicious-grandchild Job Object test, or PyO3-vs-standalone runtime benchmark is in scope; all remain implementation gates for production integration.
