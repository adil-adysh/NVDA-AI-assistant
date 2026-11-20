# Owned-process shutdown implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Stop owned LiteRT-LM, llama.cpp and UI host processes during add-on shutdown without allowing late launches.

**Architecture:** Keep process ownership in existing worker/native supervisors and host_process. Fence launches before asynchronous cleanup; use native job containment as forced-exit fallback.

**Tech stack:** Python, Windows subprocesses, existing Rust runtime supervisor.

**Spec:** ../specs/2026-11-20-mcp-startup-shutdown-tool-limit-design.md (shutdown portion authorized for this implementation).

## Constraints and review focus

External adopted servers must remain untouched. Idle executors must not be initialized for shutdown. Individual cleanup errors must not block other owners. Queued presentation must not respawn the host. Shutdown must fence executor creation and preserve command responsiveness.

## Task 1: Worker runtime cleanup

Files: worker/server.py; tests/worker/test_runtime_jobs.py.

- [x] Add failing regressions for initialized executors stopped once, cleanup failure isolation, no initialization during shutdown, and rejected post-shutdown executor access.
- [x] Run focused tests to establish failures.
- [x] Fence executor access under the existing executor lock; stop existing runtime executors with bounded timeouts during worker shutdown, retaining MCP and native job containment cleanup.
- [x] Run worker regressions and native ownership tests.

## Task 2: UI host shutdown fence

Files: ui/host_process.py; plugin/application.py; tests/ui/test_host_process_shutdown.py; tests/plugin/test_background_shutdown.py.

- [x] Add failing regressions for rejecting late launches, explicit new-application lifecycle reset, and kill fallback waiting for termination.
- [x] Introduce configure_host_lifecycle() and fence_host_startup(), synchronized with the process lock. stop_host() fences even if no process exists.
- [x] Configure on application load and fence at the beginning of terminate, before potentially blocking cleanup.
- [x] Keep cleanup independent on errors; verify application ordering and host tests.

## Task 3: Validation and documentation

- [x] Run focused worker/UI/plugin suites, Ruff and full Python tests; native supervisor tests with locked PYO3_PYTHON.
- [x] Document shutdown ownership and limits. Inspect final diff and report verified behavior without claiming a live installation.

## Task 4: User-added tool-call preference

- [x] Add config get/set_max_tool_calls with default 100, range 1–1000 and strict persisted validation.
- [x] Add translated, keyboard-accessible Behavior & Output field with help, unsaved draft handling and validation focus.
- [x] Snapshot the configured call and round limits per response through the composition root; stop repeated provider requests when call budget is exhausted.
- [x] Verify persistence, invalid values, per-turn snapshots, more than five sequential calls and call-cap exhaustion.

## Task 5: Previously requested MCP startup

- [x] Connect saved enabled servers on load using the existing bounded catalog pool.
- [x] Isolate individual failures, cancel queued startups on close, and propagate shutdown cancellation to in-flight dispatch.
- [x] Verify off-thread enabled-only startup, failure isolation, shutdown queue cancellation and application wiring.

## Execution decisions

Work continues in the shared checkout to preserve existing user edits; no commits or installation are performed. Native permanent fencing was added after review reproduced a late borrowed-reference launch race. Real-process smoke loads the new DLL directly, checks both worker executors terminate owned children, and checks external adopted servers remain reachable.
