## 2026-10-04T17:44:29Z
You are the Supervisor Test Architect Explorer for Milestone 1 (Slice 0: Rust Runtime Supervisor Concurrency Hardening).
Your working directory is: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m1_explorer_3

You MUST read the authoritative request file first:
D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\ORIGINAL_REQUEST.md
and the project specification:
D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\orchestrator_slice0_1\PROJECT.md
and the survey findings:
D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\survey_explorer_rust_1\survey_report.md.

Your mission is to formulate the exact test design and mock driver enhancements for `runtime_supervisor/src/tests.rs`:
1. Inspect the existing 11 tests in `runtime_supervisor/src/tests.rs`:
   - How `FakeProcessDriver`, `FakeProcessHandle`, and `FakeHealthChecker` are structured.
2. Design the exact test cases for:
   - RS-01: Test that simulating a child process crash or unhandled exit increments `state.generation` monotonically and transitions to `Failed`.
   - RS-01: Test that startup poll error or readiness timeout increments `state.generation`.
   - RS-02: Test that calling `ensure_ready` while `stop()` is in progress blocks until `Stopped`, and verify that `stop()` does not overwrite a new generation's state.
   - RS-03: Test that `restart()` waits for child process termination before launching replacement.
   - RS-04: Test concurrent `ensure_ready` calls with differing configs do not livelock and resolve deterministically.
   - RS-06: Test Job Object containment or mock verification.
3. Verify that these new tests integrate cleanly with the existing 11 tests in `tests.rs` without breaking any existing test.

Provide complete, compile-ready Rust test function signatures and bodies.
DO NOT modify any source files yourself.
Write your findings to:
`D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m1_explorer_3\analysis.md`
and write your completion handoff report to:
`D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m1_explorer_3\handoff.md`.
Finally, notify the orchestrator using `send_message`.
