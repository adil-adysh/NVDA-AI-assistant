# Handoff Report — Rust Runtime Supervisor Survey Phase (Slice 0)

**Sender**: Rust Runtime Supervisor Explorer (`survey_explorer_rust_1`)  
**Recipient**: Orchestrator / Implementation Agent (`72553112-d803-4b0c-aef3-2a3e71303bdb`)  
**Date**: 2026-10-04T17:38:00Z  
**Type**: Hard Handoff (Investigation Complete)  
**Deliverable Document**: `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\survey_explorer_rust_1\survey_report.md`

---

## 1. Observation

Direct observations and evidence gathered from the codebase at HEAD (`ced1cbc` and ancestors):

### 1.1 RS-01 (Generation Counter Omission)
- **`runtime_supervisor/src/supervisor.rs:130–141`** (`refresh_process_state_locked`):
  ```rust
  Ok(Some(exit_code)) => {
      state.process = None;
      if exit_code != 0 {
          state.state = LifecycleState::Failed;
          state.last_error = Some(format!(...));
      } else {
          state.state = LifecycleState::Stopped;
      }
      self.condvar.notify_all();
  }
  ```
  `state.generation` is not modified when a child process exits or crashes.
- **`runtime_supervisor/src/supervisor.rs:358–370`** (`ensure_ready` in-flight poll):
  When `proc.poll()` discovers `Ok(Some(code))`, lines 360–367 transition `s.state = LifecycleState::Failed`, set `s.last_error`, and notify `condvar`, but `s.generation` is not incremented.
- **`runtime_supervisor/src/supervisor.rs:408–428`** (`ensure_ready` readiness timeout):
  When startup timeout expires and the child has either exited or is terminated, line 421 sets `s.state = LifecycleState::Failed`, but `s.generation` is not incremented.

### 1.2 RS-02 (Missing Stopping Guard)
- **`runtime_supervisor/src/supervisor.rs:470–487`** (`stop()`):
  `stop()` increments generation to `G+1`, sets `state.state = LifecycleState::Stopping`, drops the lock at line 478, and awaits process exit via `proc.wait_timeout(timeout)` outside the mutex. At line 486, it reacquires the lock and unconditionally executes `state.state = LifecycleState::Stopped;`.
- **`runtime_supervisor/src/supervisor.rs:168–275`** (`ensure_ready()`):
  The startup loop matches `ReadyOwned` (line 173), `ReadyAdopted` (line 199), and `Starting` (line 224). There is no branch for `Stopping`. A concurrent call falling through to line 271 increments generation to `G+2`, sets `state = Starting`, and launches a new child. When `stop()` finishes, line 486 unconditionally overwrites `state.state = Stopped`, orphaning the newly spawned process as an untracked zombie.

### 1.3 RS-03 (Socket Collision on Restart)
- **`runtime_supervisor/src/supervisor.rs:448–467`** (`restart()`):
  Lines 451–453 invoke `proc.terminate()`, drop the lock at line 457, and immediately call `self.ensure_ready(...)` at line 459. Neither `proc.wait()` nor `proc.wait_timeout()` is called. Under Windows, `terminate()` invokes `TerminateProcess` asynchronously; the dying process continues holding TCP port 9379/8080 until the kernel cleans up socket handles, causing either false re-adoption in `check_compatible` or socket bind collisions (`WSAEADDRINUSE 10048`) for the replacement child.

### 1.4 RS-04 (`ensure_ready` Livelock)
- **`runtime_supervisor/src/supervisor.rs:264–268` & `314–325`**:
  If Thread 1 is in `Starting` with Config A and Thread 2 calls `ensure_ready` with Config B, line 265 immediately increments generation and supersedes Thread 1's startup. Thread 1 detects generation mismatch at line 316, kills its child, re-enters `'outer`, sees Thread 2 in `Starting`, and supersedes Thread 2. Both threads enter an unbounded ping-pong livelock.

### 1.5 RS-06 (Windows Job Object Containment)
- **`runtime_supervisor/src/process.rs:27–56`**:
  Child processes are spawned via `std::process::Command` with `CREATE_NO_WINDOW`. No Windows Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` is created or assigned to the child process handle. An abnormal crash of NVDA or the supervisor process leaks the runtime server tree.

### 1.6 RS-10 (Clean Test Shims)
- **`runtime_supervisor/src/lib.rs:1–154`**:
  Exports only `RuntimeStatus` and `RuntimeSupervisor`. Zero test mock shims exist in production PyO3 classes. All mocks (`FakeProcessHandle`, etc.) are isolated under `#[cfg(test)] mod tests;` in `tests.rs`.
- **`addon/globalPlugins/AI-assistant/providers/runtime/server.py:322–415` & `llama_server.py:91–178`**:
  Python shadow test shims (`_TestShimSupervisor` and `_LlamaTestShimSupervisor`) exist in production modules and are actively required by existing Python tests (`test_local_provider_lifecycle.py`, `test_server.py`, `test_llama_server.py`). Deleting them in Slice 0 breaks tests; their scheduled deletion is in **Slice 8**.

### 1.7 Current Baseline Test Execution
- `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml` executes 11 tests in 1.54s with 0 failures.
- `cargo check --manifest-path nvda_ui_host/Cargo.toml` passes with 0 warnings/errors.
- `uv run ruff check .` passes with 0 lint errors.
- `uv run pytest tests/providers/runtime/test_server.py` passes (38 passed in 0.33s).
- `uv run pytest tests/providers/runtime/test_llama_server.py` passes (2 passed in 0.07s).

---

## 2. Logic Chain

1. **RS-01**:
   - *Premise*: Invariant A9 requires generation fencing across epochs, guaranteeing stale health or status updates cannot overwrite newer state.
   - *Observed Fact*: `refresh_process_state_locked`, in-flight startup crash detection, and readiness timeout all transition `state.state` to `Failed` or `Stopped` without incrementing `state.generation`.
   - *Deduction*: Any client caching the previous generation or polling status will not observe an epoch boundary on crash or timeout. Stale probes from the prior epoch remain indistinguishable from the crash state.
   - *Fix*: Monotonically increment `state.generation += 1` in all three locations and notify `condvar`.

2. **RS-02**:
   - *Premise*: Invariant A7 requires native supervisor authoritative ownership and prevents resource/process leakage.
   - *Observed Fact*: `stop()` releases lock while waiting up to `timeout` seconds for process termination. Concurrently, `ensure_ready()` does not check for `Stopping` and immediately transitions to `Starting`, spawning a new process. When `stop()` finishes waiting for the old process, it unconditionally writes `state.state = LifecycleState::Stopped`.
   - *Deduction*: The newly spawned process is orphaned as an untracked zombie holding GPU memory, while the supervisor claims to be `Stopped`.
   - *Fix*: In `ensure_ready()`, block and wait on `condvar` while `state.state == LifecycleState::Stopping`. In `stop()`, guard the write to `Stopped` with `if state.generation == my_gen`.

3. **RS-03**:
   - *Premise*: Invariant A9 requires deterministic server restarts without port collisions.
   - *Observed Fact*: `restart()` invokes `proc.terminate()` without awaiting exit or port release before immediately calling `ensure_ready()`.
   - *Deduction*: `TerminateProcess` is asynchronous. The dying server may falsely satisfy `check_compatible` (causing dead adopted server state) or collide with the replacement server binding the port (`WSAEADDRINUSE 10048`).
   - *Fix*: `restart()` must invoke `proc.wait_timeout()` and poll port quiescence before launching `ensure_ready()`.

4. **RS-04**:
   - *Premise*: Concurrent calls to `ensure_ready()` must resolve deterministically without CPU saturation or runaway process spawning.
   - *Observed Fact*: Lines 264–268 supersede in-flight startups whenever the configuration differs.
   - *Deduction*: Two concurrent threads with differing configs endlessly supersede each other in an infinite ping-pong livelock.
   - *Fix*: Wait on `condvar` for the in-flight startup to complete instead of immediately superseding, and apply bounded retries.

5. **RS-06**:
   - *Premise*: Invariant A16 and Invariant A26 mandate process containment.
   - *Observed Fact*: `OsProcessDriver` does not assign spawned child processes to a Win32 Job Object.
   - *Deduction*: Parent crash leaks child process trees and GPU memory.
   - *Fix*: Assign child processes to a Win32 Job Object configured with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.

6. **RS-10**:
   - *Premise*: Invariant A7 mandates a single authoritative native owner without duplicate production test shims.
   - *Observed Fact*: `runtime_supervisor/src/lib.rs` contains zero test shims. The Python modules `server.py` and `llama_server.py` contain `_TestShimSupervisor` and `_LlamaTestShimSupervisor`, which are actively utilized by existing test suites.
   - *Deduction*: Removing the Python shims in Slice 0 would cause premature test suite regressions. The master architecture deliverable assigns Python shim removal to Slice 8. Slice 0's responsibility is locking the PyO3 interface to remain 100% clean.

---

## 3. Caveats

1. **Windows Job Object Nested Limits**: On Windows versions older than Windows 8, assigning a process that is already in a job object to another job object fails unless nested jobs are supported. On modern Windows (Windows 10/11), nested job objects are fully supported (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` operates cleanly).
2. **WinSock Port Quiescence**: Under Windows TCP/IP stack, after a listening socket handle is closed, the port is typically immediately available, but in rare edge cases (e.g. lingering client sockets in `TIME_WAIT`), a small grace period (up to 500ms) or retry loop on bind may be required.
3. **Python Test Shim Dependency**: Slice 0 must NOT delete `_TestShimSupervisor` in `server.py` or `_LlamaTestShimSupervisor` in `llama_server.py`. Deleting them before Slice 8 breaks unit and integration tests that mock the process runner.

---

## 4. Conclusion

1. **Defects Confirmed**: RS-01, RS-02, RS-03, RS-04, and RS-06 are verified code-level defects in `runtime_supervisor` with precise locations and failure mechanisms identified.
2. **Implementation Strategy Validated**: Concrete remediation designs have been developed:
   - RS-01: Monotonic generation increments in `refresh_process_state_locked`, poll failure, and timeout.
   - RS-02: `Stopping` wait in `ensure_ready` and generation-guarded state write in `stop()`.
   - RS-03: `wait_timeout` and port quiescence check in `restart()`.
   - RS-04: Condvar wait on in-flight `Starting` state for conflicting configs + bounded retries.
   - RS-06: Raw Win32 FFI or `windows` crate Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.
   - RS-10: Confirmed PyO3 module interface is clean; Python shims scheduled for Slice 8.
3. **Test Plan Ready**: 9 targeted regression tests in `runtime_supervisor/src/tests.rs` are fully specified to guard against regressions.

---

## 5. Verification Method

To independently verify the survey findings and subsequent implementation:

1. **Inspect Target Files**:
   - `runtime_supervisor/src/supervisor.rs` (lines 126–150, 168–275, 314–370, 408–428, 448–498)
   - `runtime_supervisor/src/process.rs` (lines 27–56)
   - `runtime_supervisor/src/lib.rs` (lines 1–154)
   - `addon/globalPlugins/AI-assistant/providers/runtime/server.py` (lines 322–415, 520–535)
   - `addon/globalPlugins/AI-assistant/providers/runtime/llama_server.py` (lines 91–178, 280–295)

2. **Run Cargo Tests for Runtime Supervisor**:
   ```pwsh
   uv run cargo test --manifest-path runtime_supervisor/Cargo.toml
   ```
   *Expected Current Output*: 11 passed in ~1.5s.  
   *Expected Post-Fix Output*: 20 passed (11 existing + 9 regression tests).

3. **Verify UI Host Cargo Integrity**:
   ```pwsh
   cargo check --manifest-path nvda_ui_host/Cargo.toml
   ```
   *Expected Output*: 0 errors.

4. **Verify Python Linting and Tests**:
   ```pwsh
   uv run ruff check .
   uv run pytest tests/providers/runtime/test_server.py tests/providers/runtime/test_llama_server.py
   ```
   *Expected Output*: 0 ruff errors, 40 passed in < 1.0s.

5. **Invalidation Conditions**:
   - If `state.generation` remains unchanged after simulating a crash in `status()`, RS-01 is not fixed.
   - If calling `ensure_ready()` during `stop()` spawns a child that is not tracked in `state.process`, RS-02 is not fixed.
   - If `restart()` launches a new process before `wait_timeout` is called on the old process handle, RS-03 is not fixed.
   - If two concurrent `ensure_ready()` calls with different configs loop indefinitely or spawn > 2 processes, RS-04 is not fixed.
   - If a spawned OS child process is not member of a Win32 Job Object with kill-on-close, RS-06 is not fixed.
