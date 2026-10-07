# Milestone 1 (Slice 0) Implementation Changes

**Date:** 2026-10-04  
**Author:** Implementation Worker (`m1_worker_1`)  
**Scope:** Milestone 1 / Slice 0 — Rust Runtime Supervisor Concurrency Hardening  

---

## 1. Summary of Changes

All requirements for Milestone 1 (Slice 0) have been implemented and verified:
- **RS-01 (Generation Counter Monotonicity)** in `runtime_supervisor/src/supervisor.rs`
- **RS-02 (Missing Stopping Guard)** in `runtime_supervisor/src/supervisor.rs`
- **RS-03 (Socket Collision on Restart & Teardown Quiescence)** in `runtime_supervisor/src/supervisor.rs`
- **RS-04 (`ensure_ready` Startup Livelock Mitigation)** in `runtime_supervisor/src/supervisor.rs`
- **RS-06 (Windows Job Object Containment)** in `runtime_supervisor/src/process.rs`
- **Mock Driver Upgrade & 9 New Regression Tests** in `runtime_supervisor/src/tests.rs`

---

## 2. File-by-File Changes

### 2.1 `runtime_supervisor/src/process.rs`
- **Win32 Job Object FFI Declarations (`mod win32`)**:
  - Added zero-dependency `extern "system"` bindings for `CreateJobObjectW`, `SetInformationJobObject`, `AssignProcessToJobObject`, `CloseHandle`, and `GetLastError` under `#[cfg(windows)]`.
  - Defined C-compatible struct layouts for `JOBOBJECT_EXTENDED_LIMIT_INFORMATION`, `JOBOBJECT_BASIC_LIMIT_INFORMATION`, and `IO_COUNTERS`.
  - Added `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000`.
- **RAII `JobHandle`**:
  - Encapsulated Win32 `HANDLE` with automatic cleanup in `Drop` via `CloseHandle`.
  - Implemented `Send` and `Sync` for cross-thread transfer.
- **Process Binding**:
  - Added `_job: Option<JobHandle>` to `OsProcessHandle`.
  - In `OsProcessDriver::spawn`, assigned each newly spawned child process to a Job Object configured with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.
  - If Job Object creation or assignment fails, terminates and reaps the child before returning an error.

### 2.2 `runtime_supervisor/src/supervisor.rs`
- **RS-01 Monotonic Generation Increments**:
  - In `refresh_process_state_locked`: added `state.generation += 1` on child process exit/crash.
  - In `ensure_ready` in-flight poll loop: added `s.generation += 1` when process exits unexpectedly during health polling.
  - In `ensure_ready` timeout branch: added `s.generation += 1` when readiness timeout expires.
  - In `ensure_ready` spawn error branch: added `state.generation += 1` when child spawn fails.
- **RS-02 Stopping State Coordination & State Guard**:
  - In `ensure_ready`: added wait loop on `self.condvar` while `state.state == LifecycleState::Stopping || state.state == LifecycleState::Restarting`, preventing premature spawning of zombie processes.
  - In `stop()`: captured entry generation `let my_gen = state.generation` and guarded terminal write `if state.generation == my_gen { state.state = LifecycleState::Stopped; }`, preventing stale stops from clobbering newer active epochs.
- **RS-03 5-Phase Restart Sequence**:
  - Restructured `restart()` into 5 distinct phases:
    1. Enter `Restarting` under lock, increment generation, take old process handle, broadcast condvar notification, drop lock.
    2. Await process exit via `old_proc.wait_timeout(drain_timeout)`.
    3. Port quiescence verification: poll `!health_checker.check_health()` until false or quiescence deadline expires.
    4. Transition state to `Stopped` under lock and broadcast condvar notification.
    5. Calculate remaining timeout and call `ensure_ready`.
- **RS-04 Startup Livelock Mitigation**:
  - In `ensure_ready`: replaced preemption and immediate killing of in-flight startup with condvar wait regardless of configuration.
  - Callers with identical configuration return immediately once terminal ready state is reached.
  - Callers with differing configuration wait until in-flight startup completes, then cleanly transition to `restart()` or start from scratch without process ping-pong.
  - Added bounded retry loop (`MAX_ATTEMPTS = 5`) and exponential backoff (`50ms * 2^attempt`) on post-spawn generation collisions.

### 2.3 `runtime_supervisor/src/tests.rs`
- **Mock Driver Enhancements**:
  - `FakeProcessHandle`: added `wait_delay_ms`, `wait_called`, `wait_completed`, and `poll_error`.
  - `FakeProcessDriver`: added `wait_delay_ms`, `last_wait_called`, `last_wait_completed`, `spawn_delay_ms`, and `poll_error`.
  - `FakeHealthChecker`: added `become_unhealthy_after` for shutdown endpoint release simulation.
  - Maintained 100% backward compatibility with all 11 existing tests.
- **9 New Regression Tests Added**:
  1. `test_child_crash_increments_generation_monotonically` (RS-01)
  2. `test_startup_child_crash_increments_generation` (RS-01)
  3. `test_startup_readiness_timeout_increments_generation` (RS-01)
  4. `test_ensure_ready_blocks_and_waits_if_stopping` (RS-02)
  5. `test_stop_generation_guard_preserves_concurrent_epoch` (RS-02)
  6. `test_restart_waits_for_child_process_termination` (RS-03)
  7. `test_restart_does_not_adopt_dying_server` (RS-03)
  8. `test_concurrent_ensure_ready_differing_configs_no_livelock` (RS-04)
  9. `test_os_process_handle_job_object_containment` (RS-06)

---

## 3. Verification Commands and Results

| Command | Status | Output Details |
|---|---|---|
| `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml` | **PASS** | 20 passed; 0 failed; 0 ignored; finished in 1.55s |
| `cargo check --manifest-path nvda_ui_host/Cargo.toml` | **PASS** | Finished `dev` profile in 0.03s, 0 errors |
| `uv run ruff check .` | **PASS** | All checks passed, 0 errors |
| `uv run pytest` | **PASS** | 461 passed, 3 deselected in 13.12s |
