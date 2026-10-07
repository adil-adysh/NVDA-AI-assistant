## 2026-10-04T17:44:29Z
You are the Supervisor State & Concurrency Explorer for Milestone 1 (Slice 0: Rust Runtime Supervisor Concurrency Hardening).
Your working directory is: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m1_explorer_1

You MUST read the authoritative request file first:
D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\ORIGINAL_REQUEST.md
and the project specification:
D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\orchestrator_slice0_1\PROJECT.md
and the survey findings:
D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\survey_explorer_rust_1\survey_report.md.

Your mission is to formulate an exact, code-level fix strategy for:
1. RS-01 (Generation Counter Monotonicity):
   - In `runtime_supervisor/src/supervisor.rs`, analyze exact lines where `state.generation` must be incremented:
     - `refresh_process_state_locked`: when process poll indicates child exited or crashed
     - `ensure_ready` in-flight poll loop: when child process has terminated unexpectedly
     - `ensure_ready` startup timeout branch: when startup poll times out
   - Detail the exact state mutation and `condvar.notify_all()` sequence.
2. RS-02 (Missing Stopping Guard):
   - In `runtime_supervisor/src/supervisor.rs`, detail the condvar wait logic in `ensure_ready` when `state.state == LifecycleState::Stopping`.
   - In `stop()`, detail how to capture generation (`my_gen = state.generation`) and guard the write to `LifecycleState::Stopped` so that if generation has changed, it does not overwrite active state.
3. RS-04 (`ensure_ready` Livelock Mitigation):
   - In `runtime_supervisor/src/supervisor.rs`, detail how competing calls in `Starting` state with differing configs should wait on `condvar` for startup completion rather than preempting each other immediately, plus exponential backoff retry bounds.

Provide exact Rust pseudocode, signatures, lock handling, and condvar notification patterns.
DO NOT modify any source files yourself (you are read-only).
Write your findings to:
`D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m1_explorer_1\analysis.md`
and write your completion handoff report to:
`D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m1_explorer_1\handoff.md`.
Finally, notify the orchestrator using `send_message`.
