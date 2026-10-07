# Milestone 1 (Slice 0: Rust Runtime Supervisor Concurrency Hardening) Handoff Report

**Date:** 2026-10-04  
**Author:** Reviewer 2 (`m1_reviewer_2` — Reviewer & Adversarial Critic)  
**Scope:** Review and Adversarial Critique of Milestone 1 / Slice 0  
**Recipient:** Orchestrator (`72553112-d803-4b0c-aef3-2a3e71303bdb`)  
**Verdict:** **APPROVE**  

---

## 1. Observation

1. **RS-06 (Win32 Job Object Containment)**:
   - In `runtime_supervisor/src/process.rs:12–71`, `mod win32` defines standard FFI bindings for `CreateJobObjectW`, `SetInformationJobObject`, `AssignProcessToJobObject`, `CloseHandle`, and `GetLastError` under `#[cfg(windows)]`.
   - In `runtime_supervisor/src/process.rs:20`, `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` is defined as `0x00002000`.
   - In `runtime_supervisor/src/process.rs:73–137`, `JobHandle` encapsulates `win32::HANDLE` with RAII `Drop` invoking `CloseHandle(self.0)`.
   - In `runtime_supervisor/src/process.rs:180–197`, `OsProcessDriver::spawn` creates a Job Object configured with `KILL_ON_JOB_CLOSE` and assigns the newly spawned child process (`child.as_raw_handle()`). On failure, the child is killed and reaped before returning an error.
   - In `runtime_supervisor/src/process.rs:208–213`, `OsProcessHandle` retains ownership of `_job: Option<JobHandle>` under `#[cfg(windows)]`.

2. **RS-10 (PyO3 Cleanliness)**:
   - In `runtime_supervisor/src/lib.rs:1–154`, `RuntimeSupervisor` and `RuntimeStatus` are exported via `#[pymethods]` with zero mock drivers, fake health checkers, or test-only shims.
   - Driver injection is internal to the Rust crate via `SupervisorCore::with_drivers` in `supervisor.rs:49`, strictly inaccessible from Python.

3. **Regression Test Suite**:
   - In `runtime_supervisor/src/tests.rs:1–924`, 20 tests are present: all 11 original tests plus 9 new regression tests.
   - `test_os_process_handle_job_object_containment` (`tests.rs:874–923`) executes a real OS process and verifies containment via live Win32 `IsProcessInJob` syscall.
   - All 9 new tests test concrete concurrency edge cases with non-vacuous assertions.

4. **Independent Tool Verification Results**:
   - `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml`:
     ```
     running 20 tests
     test tests::test_adopted_server_detected_and_reused ... ok
     test tests::test_child_crash_increments_generation_monotonically ... ok
     test tests::test_adopted_server_disappears_triggers_spawn ... ok
     test tests::test_child_exits_after_becoming_ready ... ok
     test tests::test_child_exits_immediately_after_spawn ... ok
     test tests::test_wrong_unrelated_server_on_endpoint_is_not_adopted ... ok
     test tests::test_os_process_handle_job_object_containment ... ok
     test tests::test_startup_child_crash_increments_generation ... ok
     test tests::test_stop_during_startup_cancels_cleanly ... ok
     test tests::test_stop_generation_guard_preserves_concurrent_epoch ... ok
     test tests::test_ensure_ready_blocks_and_waits_if_stopping ... ok
     test tests::test_startup_readiness_timeout_increments_generation ... ok
     test tests::test_simultaneous_ensure_ready_calls_deduplicate ... ok
     test tests::test_config_change_restarts_running_server ... ok
     test tests::test_restart_does_not_adopt_dying_server ... ok
     test tests::test_stale_generation_does_not_overwrite_newer_state ... ok
     test tests::test_concurrent_ensure_ready_differing_configs_no_livelock ... ok
     test tests::test_os_process_driver_exit_code ... ok
     test tests::test_restart_waits_for_child_process_termination ... ok
     test tests::test_ensure_ready_with_os_process_child_exit ... ok

     test result: ok. 20 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 1.54s
     ```
   - `cargo check --manifest-path nvda_ui_host/Cargo.toml`:
     ```
     Finished `dev` profile [optimized + debuginfo] target(s) in 0.03s (0 errors)
     ```
   - `uv run ruff check .`:
     ```
     All checks passed! (0 errors)
     ```
   - `uv run pytest`:
     ```
     461 passed, 3 deselected in 12.48s (0 failures)
     ```

---

## 2. Logic Chain

1. **Containment Safety (RS-06)**:
   - Direct inspection of `process.rs` confirms that `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x00002000)` is applied to an anonymous job object created with default security attributes (`bInheritHandle = FALSE`).
   - Child processes are assigned to the Job Object immediately upon creation. If `AssignProcessToJobObject` fails, the child is terminated synchronously via `child.kill()` and reaped via `child.wait()`.
   - The job handle is retained in `OsProcessHandle._job` and closed upon drop via `CloseHandle`. If the parent NVDA process crashes or terminates abnormally, the Windows kernel closes all process handles, triggering termination of all assigned child processes.
   - This eliminates orphaned server processes and GPU VRAM leaks.

2. **PyO3 Boundary Cleanliness (RS-10)**:
   - Inspection of `lib.rs` and `types.rs` demonstrates that the exposed PyO3 surface contains only production methods.
   - Test hooks and fake drivers exist solely within `#[cfg(test)] mod tests;` and internal crate constructors, completely isolated from runtime and Python caller access.

3. **Regression Test Integrity**:
   - The 9 new regression tests systematically reproduce and verify the resolution of RS-01, RS-02, RS-03, RS-04, and RS-06.
   - No mock bypasses, hardcoded return shims, or facade tests were detected.
   - Backwards compatibility is preserved for all 11 existing baseline tests.

4. **Zero Regressions**:
   - Pytest suite of 461 tests, ruff linter, cargo test suite, and native UI host build checks pass with zero errors.

---

## 3. Caveats

- **Windows Platform Scope**: Win32 Job Object containment is guarded by `#[cfg(windows)]`. On non-Windows platforms, process tracking proceeds without Job Objects. Because NVDA is exclusively a Windows application, this platform scoping is appropriate.
- **Nested Job Support**: Nested Job Objects require Windows 8+ (supported natively up to 32 levels). Since NVDA 2024.1+ mandates Windows 10+, this requirement is fully satisfied in all supported environments.

---

## 4. Conclusion

**Verdict: APPROVE**

Milestone 1 (Slice 0: Rust Runtime Supervisor Concurrency Hardening) satisfies all functional requirements and architectural invariants. RS-06 Win32 Job Object containment, RS-10 PyO3 interface cleanliness, and the 20-test regression suite are implemented correctly, cleanly, and without any integrity violations or regressions.

---

## 5. Verification Method

To independently reproduce and verify this review:
1. Run the Rust runtime supervisor test suite:
   ```powershell
   uv run cargo test --manifest-path runtime_supervisor/Cargo.toml
   ```
   *Expected:* 20 passed; 0 failed in ~1.5s.
2. Verify native UI host compilation:
   ```powershell
   cargo check --manifest-path nvda_ui_host/Cargo.toml
   ```
   *Expected:* Exit code 0, 0 errors.
3. Verify Python linter:
   ```powershell
   uv run ruff check .
   ```
   *Expected:* "All checks passed!"
4. Verify complete Python test suite:
   ```powershell
   uv run pytest
   ```
   *Expected:* 461 passed, 3 deselected, 0 failures.
5. Invalidation conditions: Any test failure in `runtime_supervisor/src/tests.rs` or presence of non-production mock APIs in `runtime_supervisor/src/lib.rs`.
