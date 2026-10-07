## 2026-10-04T17:50:50Z
You are the Implementation Worker for Milestone 1 (Slice 0: Rust Runtime Supervisor Concurrency Hardening).
Your working directory is: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m1_worker_1

You MUST read the authoritative request file first:
D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\ORIGINAL_REQUEST.md
and the project specification:
D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\orchestrator_slice0_1\PROJECT.md

Read the three Explorer analysis reports that provide the exact code designs and test architectures:
1. D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m1_explorer_1\analysis.md (RS-01, RS-02, RS-04 state machine, generation fencing, condvar guards)
2. D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m1_explorer_2\analysis.md (RS-03 socket quiescence & restart, RS-06 Win32 Job Object containment with KILL_ON_JOB_CLOSE)
3. D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m1_explorer_3\analysis.md (Enhanced mock drivers and 9 new regression tests in tests.rs)

WRITE OWNERSHIP:
You exclusively own and may modify ONLY these files:
- runtime_supervisor/src/supervisor.rs
- runtime_supervisor/src/process.rs
- runtime_supervisor/src/tests.rs

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

YOUR TASKS:
1. In `runtime_supervisor/src/supervisor.rs`:
   - Implement RS-01: Monotonic generation increment (`state.generation += 1`) in `refresh_process_state_locked` on child exit/crash, in `ensure_ready` in-flight poll exit, and in startup timeout branch.
   - Implement RS-02: Condvar wait in `ensure_ready` while `state.state == LifecycleState::Stopping`, and generation-guarded state write in `stop()` (`if state.generation == my_gen { state.state = LifecycleState::Stopped; }`).
   - Implement RS-03: `restart()` 5-phase sequence: terminate, await exit via `proc.wait_timeout()`, check port quiescence via `health_checker.check_health()`, and condvar wait in `ensure_ready` while `LifecycleState::Restarting`.
   - Implement RS-04: Differing config startup synchronization: wait on condvar for in-flight `Starting` to reach terminal state rather than prematurely superseding, and bounded retry loop with exponential backoff on collisions.
2. In `runtime_supervisor/src/process.rs`:
   - Implement RS-06: Windows Job Object assignment with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` using zero-dependency raw Win32 FFI under `#[cfg(windows)]`. Maintain RAII Job Object handle ownership in `OsProcessHandle`.
3. In `runtime_supervisor/src/tests.rs`:
   - Upgrade `FakeProcessHandle`, `FakeProcessDriver`, and `FakeHealthChecker` per Explorer 3's design with 100% backward compatibility.
   - Implement the 9 new regression tests covering RS-01, RS-02, RS-03, RS-04, and RS-06.
4. Run verification commands:
   - `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml` (all 20 tests must pass 100%)
   - `cargo check --manifest-path nvda_ui_host/Cargo.toml` (must pass with 0 errors)
   - `uv run ruff check .` (must pass with 0 errors)

Document your changes, build/test results, and verification output in:
`D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m1_worker_1\changes.md`
and write your completion handoff report to:
`D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m1_worker_1\handoff.md`.
Finally, notify the orchestrator using `send_message`.
