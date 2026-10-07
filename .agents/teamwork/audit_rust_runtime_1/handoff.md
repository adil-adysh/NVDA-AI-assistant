# Handoff Report: Rust Runtime & Concurrency Audit (Audit E, Invariants A7–A10, A25–A26)

- **Agent**: Rust Runtime & Concurrency Auditor (Agent 3)
- **Working Directory**: `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\audit_rust_runtime_1`
- **Target Report**: `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\audit_rust_runtime_1\audit_report.md`
- **Commit HEAD**: `ced1cbc`
- **Recipient**: Orchestrator (`c9e0cb5b-a18e-419f-bdcf-b2ee7418887c`)

---

## 1. Observation

Direct observations from the repository at HEAD (`ced1cbc`):

### 1.1 Generation Fencing Omissions on Crash & Timeout
In `runtime_supervisor/src/supervisor.rs`:
- Lines 129–142 (`refresh_process_state_locked`):
  ```rust
  match process.poll() {
      Ok(Some(exit_code)) => {
          state.process = None;
          if exit_code != 0 {
              state.state = LifecycleState::Failed;
              state.last_error = Some(format!(
                  "{} server process exited unexpectedly with code {}",
                  self.runtime_name, exit_code
              ));
          } else {
              state.state = LifecycleState::Stopped;
          }
          self.condvar.notify_all();
      }
  ```
  `state.generation` is not incremented upon unexpected child exit.
- Lines 358–368 (premature exit in health loop): `s.state = LifecycleState::Failed;` without `s.generation += 1`.
- Lines 421–428 (readiness timeout): `s.state = LifecycleState::Failed;` without `s.generation += 1`.

### 1.2 Missing `Stopping` Guard in `ensure_ready` & State Overwrite in `stop()`
In `runtime_supervisor/src/supervisor.rs`:
- Lines 168–275: `ensure_ready` checks `ReadyOwned` (173), `ReadyAdopted` (199), and `Starting` (224). There is no guard for `LifecycleState::Stopping`. When `state.state == LifecycleState::Stopping`, it falls through to line 271:
  ```rust
  state.generation += 1;
  let my_gen = state.generation;
  state.state = LifecycleState::Starting;
  ```
  This immediately initiates spawning a new child process while the old process is still being terminated by `stop()`.
- Lines 485–487 (`stop`):
  ```rust
  let mut state = self.state.lock().unwrap();
  state.state = LifecycleState::Stopped;
  self.condvar.notify_all();
  ```
  `stop()` assigns `state.state = LifecycleState::Stopped` unconditionally without checking `if state.generation == my_gen`.

### 1.3 `restart()` Does Not Await Process Exit Before Re-launch
In `runtime_supervisor/src/supervisor.rs`:
- Lines 448–466:
  ```rust
  pub fn restart(...) -> Result<RuntimeStatus, String> {
      let mut state = self.state.lock().unwrap();
      state.generation += 1;
      state.state = LifecycleState::Restarting;
      if let Some(mut proc) = state.process.take() {
          let _ = proc.terminate();
      }
      state.startup_identity = None;
      state.running_model = None;
      self.condvar.notify_all();
      drop(state);

      self.ensure_ready(...)
  }
  ```
  `restart()` drops `proc` immediately after `proc.terminate()` without calling `proc.wait_timeout()` or polling socket availability.

### 1.4 Livelock on Concurrent Conflicting `ensure_ready`
In `runtime_supervisor/src/supervisor.rs`:
- Lines 264–268: A differing configuration increments `state.generation += 1` and takes `state.process`.
- Lines 314–325: The superseded thread sees `state.generation != my_gen`, kills its newly spawned child, and executes `continue 'outer;`. In `'outer`, it sees the other thread's `Starting` state as differing, increments generation, and restarts its spawn.

### 1.5 Absence of Model Identity Checking in Adoption
In `runtime_supervisor/src/health.rs`:
- Lines 32–63: `check_compatible` verifies only that `/v1/models` (or `/models`) returns HTTP 200 with JSON key `"data"` or `"models"`. It does not accept or verify `expected_model`.
In `runtime_supervisor/src/supervisor.rs`:
- Lines 199–221: When in `ReadyAdopted`, `ensure_ready` verifies only `check_health` without checking `startup_identity`. Any configuration changes applied by the user are ignored.

### 1.6 Production Modules Contain Duplicate Shadow Test Shims
- `addon/globalPlugins/AI-assistant/providers/runtime/server.py:322–415`: `_TestShimSupervisor` implements an unverified pure-Python shadow supervisor.
- `addon/globalPlugins/AI-assistant/providers/runtime/llama_server.py:191–258`: `_LlamaTestShimSupervisor` implements another pure-Python shadow supervisor.

### 1.7 Verification Commands and Results
- `$env:PYO3_USE_ABI3_FORWARD_COMPATIBILITY="1"; cargo test --manifest-path runtime_supervisor/Cargo.toml`:
  Output: `11 passed; 0 failed; 0 ignored; finished in 1.54s`
- `uv run pytest tests/providers/runtime/test_runtime_supervisor.py`:
  Output: `12 passed in 11.28s`

---

## 2. Logic Chain

1. **Premise**: Invariant A9 mandates that generation fencing must prevent zombie/orphaned processes and stale status overwrites.
2. **Step 1 (Crash Observation)**: Observation 1.1 proves that when a process exits unexpectedly with non-zero exit code or times out, `state.state` transitions to `Failed`, but `state.generation` remains unchanged.
3. **Inference 1**: Any client relying on `generation` monotonicity to detect lifecycle events will fail to recognize that the process died and transitioned into a failure epoch.
4. **Step 2 (Stopping Race Observation)**: Observation 1.2 demonstrates that `ensure_ready` has no branch handling `LifecycleState::Stopping`. If thread B calls `ensure_ready` while thread A is in `stop()` awaiting process exit, thread B spawns child $P_2$ and marks state `ReadyOwned`.
5. **Inference 2**: When thread A finishes `proc.wait_timeout`, it unconditionally executes `state.state = LifecycleState::Stopped`. This overwrites thread B's `ReadyOwned` state without checking generation. $P_2$ is leaked as an untracked orphan in the OS while `status()` reports `Stopped`.
6. **Step 3 (Restart Race Observation)**: Observation 1.3 shows `restart()` fires `proc.terminate()` (which is non-blocking `TerminateProcess`) and immediately calls `ensure_ready` without waiting for process exit or port release.
7. **Inference 3**: If the terminating process takes 50–200ms to unbind its socket, the new child process crashes with `WSAEADDRINUSE` (10048), or `check_compatible` mistakenly re-adopts the dying process.
8. **Step 4 (Livelock Observation)**: Observation 1.4 shows two competing threads with different configs repeatedly increment generation, kill the opposing child, and loop via `continue 'outer`.
9. **Inference 4**: Concurrent callers requesting different models or configurations will livelock each other.
10. **Step 5 (Adoption Trap Observation)**: Observation 1.5 shows `check_compatible` checks only for `"data"` key and never validates model ID; once adopted, `ensure_ready` never checks config changes.
11. **Inference 5**: An adopted server can never be reconfigured or restarted through the supervisor.
12. **Step 6 (Invariant A7 Observation)**: Observation 1.6 shows duplicate Python shims inside production files `server.py` and `llama_server.py`.
13. **Inference 6**: Violates Invariant A7 (native supervisor as single authoritative owner of runtime mechanics).

---

## 3. Caveats

- **No Caveats on Local Implementation**: The `runtime_supervisor` codebase, PyO3 bindings, and Python callers were fully reviewed line-by-line.
- **Windows-Specific Process Behavior**: Testing was performed on Windows 11 x64. Process creation flags (`CREATE_NO_WINDOW`) and `TerminateProcess` behavior are specific to the Windows platform (the target deployment OS for NVDA).
- **Python 3.14 Cargo Test Pre-condition**: Running `cargo test` directly on machines with Python 3.14 preview requires `$env:PYO3_USE_ABI3_FORWARD_COMPATIBILITY="1"`; `scripts/build.py` already includes this flag.

---

## 4. Conclusion

1. The current `runtime_supervisor` crate provides essential baseline capabilities (GIL release, frozen immutable status snapshots, deduplication for identical concurrent callers), but contains **four critical BLOCKER concurrency bugs**:
   - RS-01: Stale generation on child crash/timeout.
   - RS-02: Missing `Stopping` guard causing state overwrite and zombie processes.
   - RS-03: `restart()` port race and false re-adoption.
   - RS-04: Conflicting startup ping-pong livelock.
2. Invariant A7 is violated by the presence of `_TestShimSupervisor` and `_LlamaTestShimSupervisor` in production Python modules.
3. Invariants A25–A26 are violated because `RuntimeSupervisor` currently runs inside `nvda.exe` rather than inside the dedicated Worker boundary.
4. All findings have been fully documented with exact line numbers and classifications in `audit_report.md`. Remediation must be executed in Slice 0 / Pre-implementation before moving runtime ownership to the Worker in Slices 6–8.

---

## 5. Verification Method

To independently verify all findings and test suite execution:

1. **Verify Rust Test Suite**:
   ```powershell
   $env:PYO3_USE_ABI3_FORWARD_COMPATIBILITY="1"
   cargo test --manifest-path runtime_supervisor/Cargo.toml
   ```
   Confirm all 11 tests pass.

2. **Verify Python Supervisor Test Suite**:
   ```powershell
   uv run pytest tests/providers/runtime/test_runtime_supervisor.py
   ```
   Confirm all 12 tests pass.

3. **Inspect RS-01 Stale Generation**:
   Examine `runtime_supervisor/src/supervisor.rs:130–141`, `361`, `421`. Verify absence of `state.generation += 1`.

4. **Inspect RS-02 State Overwrite**:
   Examine `runtime_supervisor/src/supervisor.rs:168–275` (lack of `Stopping` check) and lines `485–487` (unconditional assignment to `Stopped`).

5. **Inspect RS-03 `restart()` Race**:
   Examine `runtime_supervisor/src/supervisor.rs:448–467`. Verify `proc.wait_timeout()` is missing before `self.ensure_ready()`.

6. **Inspect RS-10 Shadow Test Shims**:
   Examine `addon/globalPlugins/AI-assistant/providers/runtime/server.py:322–415` and `addon/globalPlugins/AI-assistant/providers/runtime/llama_server.py:191–258`.
