## 2026-10-04T17:44:29Z

You are the Process Containment & Socket Explorer for Milestone 1 (Slice 0: Rust Runtime Supervisor Concurrency Hardening).
Your working directory is: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m1_explorer_2

You MUST read the authoritative request file first:
D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\ORIGINAL_REQUEST.md
and the project specification:
D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\orchestrator_slice0_1\PROJECT.md
and the survey findings:
D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\survey_explorer_rust_1\survey_report.md.

Your mission is to formulate an exact, code-level fix strategy for:
1. RS-03 (Socket Collision on Restart):
   - In `runtime_supervisor/src/supervisor.rs`, inspect `restart()`:
   - Design the exact sequence: `proc.terminate()`, awaiting process exit via `proc.wait_timeout(timeout)`, checking exit status, and checking port quiescence (verifying port is released before launching `ensure_ready`).
   - Define timeouts and error handling if process fails to terminate.
2. RS-06 (Windows Job Object Containment):
   - In `runtime_supervisor/src/process.rs`, analyze how `OsProcessDriver::spawn` spawns child processes using `std::process::Command`.
   - Formulate the exact implementation of a Win32 Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.
   - Determine how to bind the Job Object to the child process handle (or create the child suspended/assign to Job Object/resume, or `AssignProcessToJobObject` immediately after spawn).
   - Check dependencies in `runtime_supervisor/Cargo.toml`: whether to use raw Win32 FFI via `windows-sys` or `winapi`, or zero-dependency `extern "system"` bindings for `CreateJobObjectW`, `SetInformationJobObject`, `AssignProcessToJobObject`, `CloseHandle`. Provide the exact struct definitions and constants (`JOBOBJECT_EXTENDED_LIMIT_INFORMATION`, `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, etc.).
   - Ensure clean cross-platform compilation (`#[cfg(windows)]` and no-op on non-Windows).

Provide exact Rust pseudocode and Cargo dependencies needed.
DO NOT modify any source files yourself.
Write your findings to:
`D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m1_explorer_2\analysis.md`
and write your completion handoff report to:
`D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m1_explorer_2\handoff.md`.
Finally, notify the orchestrator using `send_message`.
