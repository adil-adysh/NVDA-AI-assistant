# Adversarial Challenge Report — Milestone 1 (Slice 0)

**Challenger:** Empirical Challenger 1 (`m1_challenger_1`)  
**Scope:** RS-01 (Monotonic Generation Fencing) and RS-02 (Stopping Synchronization & Orphan Prevention)  
**Date:** 2026-10-04  
**Subject:** `runtime_supervisor` (HEAD + Slice 0 modifications)

---

## 1. Challenge Summary

**Overall risk assessment:** LOW (Robust against concurrency hazards RS-01 & RS-02)

Empirical evaluation and adversarial testing confirm that:
1. **RS-01 Generation Monotonicity**: State transitions triggered by child process crashes, abnormal terminations, health polling failures, and readiness timeouts strictly increment `state.generation`. Downstream callers querying `status()` observe strictly increasing generation numbers across crash events, and subsequent read-only queries are stable and do not falsely re-increment generation.
2. **RS-02 Stopping Synchronization & Orphan Prevention**: Calling `ensure_ready()` while `stop()` is in progress blocks on the internal condvar until `stop()` finishes process termination and port teardown. No orphaned child processes or zombie handles are spawned. Furthermore, `stop()` guards its terminal state write with `if state.generation == my_gen`, preventing a delayed `stop()` execution from clobbering an active newer epoch back to `Stopped`.

---

## 2. Adversarial Hypotheses & Findings

### Challenge 1: Generation Counter Stagnation or Spurious Increments on Child Crash (RS-01)

- **Assumption Challenged**: Child process crashes and abnormal exits increment `generation` monotonically and atomically, and repeated read-only queries do not spuriously re-increment the counter.
- **Attack Scenario**:
  1. A running server process in `ReadyOwned` state crashes or is forcefully killed (`exit_code = 137`).
  2. Multiple concurrent callers or a tight watchdog loop invoke `status()` to inspect runtime health.
  3. *Failure Mode A*: If `refresh_process_state_locked` fails to increment `generation`, the generation remains unchanged, leading downstream consumers (cache managers, watchdog monitors) to mistake the crash for the previous healthy generation.
  4. *Failure Mode B*: If `refresh_process_state_locked` increments `generation` on *every* call to `status()` even after the process handle has been reaped, generation numbers drift indefinitely without state changes.
- **Empirical Test & Code Audit**:
  - In `runtime_supervisor/src/supervisor.rs:130-143`:
    ```rust
    match process.poll() {
        Ok(Some(exit_code)) => {
            state.process = None;
            state.generation += 1;
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
        ...
    }
    ```
  - `state.process` is set to `None` atomically under `state.lock().unwrap()`.
  - When subsequent calls to `status()` occur, `if let Some(ref mut process) = state.process` evaluates to `false`. The counter is incremented exactly once upon detecting process exit, and remains stable across all subsequent queries.
  - In `test_child_crash_increments_generation_monotonically`:
    - Initial `ReadyOwned`: `generation = 1`.
    - Crash simulated (`current_alive = false`, `exit_code = 137`).
    - First query: `state = "failed"`, `generation = 2` (strictly greater).
    - Second query: `state = "failed"`, `generation = 2` (stable, no spurious increment).
  - Multi-cycle stress test (`test_adversarial_crash_loop_generation_monotonicity`):
    - Executed 10 consecutive crash-restart cycles. In all 10 cycles, `G_crash > G_ready > G_previous_crash` held strictly monotonically. Across 5 repeated `status()` queries per cycle, generation remained strictly invariant.
- **Result**: PASSED. Hypothesis rejected; implementation is robust.

---

### Challenge 2: Zombie / Orphan Process Spawning During Active Teardown (RS-02)

- **Assumption Challenged**: Concurrent calls to `ensure_ready()` while `stop()` is executing must block until teardown completes, preventing two simultaneous process instances on the same endpoint.
- **Attack Scenario**:
  1. Process A is running. Thread 1 initiates `stop()`.
  2. `stop()` transitions state to `LifecycleState::Stopping` and initiates process termination.
  3. While Thread 1 is awaiting exit in `proc.wait_timeout(timeout)`, Thread 2 invokes `ensure_ready()`.
  4. If `ensure_ready()` fails to wait for `Stopping` to finish, Thread 2 spawns a replacement process (Process B) while Process A is still alive and bound to the socket, leading to `WSAEADDRINUSE` port collision and duplicate/orphaned server processes.
- **Empirical Test & Code Audit**:
  - In `runtime_supervisor/src/supervisor.rs:184-212`:
    ```rust
    if state.state == LifecycleState::Stopping || state.state == LifecycleState::Restarting {
        let my_gen = state.generation;
        let remaining = timeout.saturating_sub(start_time.elapsed());
        if remaining.is_zero() {
            return Err(format!(
                "Timed out waiting for {} server to finish {}",
                self.runtime_name,
                if state.state == LifecycleState::Stopping { "stopping" } else { "restarting" }
            ));
        }
        let (new_state, wait_res) = self
            .condvar
            .wait_timeout_while(state, remaining, |s| {
                (s.state == LifecycleState::Stopping || s.state == LifecycleState::Restarting)
                    && s.generation == my_gen
            })
            .unwrap();
        state = new_state;
        ...
        continue 'outer;
    }
    ```
  - Thread 2 enters `wait_timeout_while` on `self.condvar` while `state.state == Stopping`.
  - When Thread 1 finishes terminating Process A, it acquires the mutex, sets `state.state = LifecycleState::Stopped`, and invokes `self.condvar.notify_all()`.
  - Thread 2 wakes up, checks `s.state`, and restarts `'outer: loop` with `state.state == Stopped`, proceeding cleanly to spawn Process B only *after* Process A has exited.
  - In `test_ensure_ready_blocks_and_waits_if_stopping`:
    - Process A delay configured to 150ms in `wait_timeout`.
    - Thread 1 initiates `stop()`.
    - Thread 2 invokes `ensure_ready()`.
    - Thread 1 completes `stop()`.
    - Thread 2 completes `ensure_ready()`.
    - Total process spawns: exactly 2 (initial process + replacement process). Zero orphaned processes.
  - In adversarial timing test (`test_adversarial_ensure_ready_blocks_until_stop_completes`):
    - `start_instant.elapsed()` measured on Thread 2: elapsed >= 100ms, proving empirical blocking on condvar rather than premature execution.
- **Result**: PASSED. Hypothesis rejected; implementation is robust.

---

### Challenge 3: Epoch Clobbering by Stale Stop (RS-02)

- **Assumption Challenged**: An in-flight `stop()` execution must not overwrite `state.state = Stopped` if another thread has advanced the generation and started a newer epoch.
- **Attack Scenario**:
  1. Thread 1 initiates `stop()` on Generation G1, advancing generation to G2 (`Stopping`).
  2. Thread 1 drops mutex to execute `proc.wait_timeout(timeout)`.
  3. While Thread 1 is waiting, Thread 2 initiates `stop()` or `restart()` or `adopt()`, advancing generation to G3.
  4. Thread 1 completes `wait_timeout` and re-acquires lock.
  5. If Thread 1 unconditionally writes `state.state = Stopped`, it clobbers Generation G3's active state.
- **Empirical Test & Code Audit**:
  - In `runtime_supervisor/src/supervisor.rs:605-626`:
    ```rust
    let mut state = self.state.lock().unwrap();
    state.generation += 1;
    let my_gen = state.generation;
    state.state = LifecycleState::Stopping;
    let mut proc_opt = state.process.take();
    ...
    drop(state);

    if let Some(ref mut proc) = proc_opt {
        let _ = proc.terminate();
        let _ = proc.wait_timeout(timeout);
    }

    let mut state = self.state.lock().unwrap();
    if state.generation == my_gen {
        state.state = LifecycleState::Stopped;
        self.condvar.notify_all();
    }
    ```
  - Thread 1 checks `if state.generation == my_gen`. If generation has changed (e.g. G3 != G2), the state write is skipped.
  - In `test_stop_generation_guard_preserves_concurrent_epoch`:
    - Initial startup to `ReadyOwned` (`generation = 1`).
    - Thread A calls `stop()` with 120ms delay.
    - Thread B calls `ensure_ready()` with config-v2.
    - Verified final state is `ReadyOwned` with config-v2, `generation >= 3`, NOT clobbered back to `Stopped`.
  - In `test_adversarial_stop_race_preserves_latest_epoch`:
    - Two concurrent `stop()` calls with delayed termination complete cleanly, reaching `Stopped` with `generation >= 3`.
- **Result**: PASSED. Hypothesis rejected; implementation is robust.

---

## 3. Stress Test Results

| Test Scenario | Target | Expected Behavior | Actual Behavior | Result |
|---|---|---|---|---|
| `test_child_crash_increments_generation_monotonically` | RS-01 | Generation increments strictly on crash; stable on subsequent queries | Gen 1 -> Gen 2; repeated queries return Gen 2 | **PASS** |
| `test_startup_child_crash_increments_generation` | RS-01 | Crash during startup poll loop increments generation and fails | Gen >= 2, state = failed | **PASS** |
| `test_startup_readiness_timeout_increments_generation` | RS-01 | Startup timeout increments generation and reaps process | Gen >= 2, state = failed, err contains timeout | **PASS** |
| `test_adversarial_crash_loop_generation_monotonicity` | RS-01 | 10 crash cycles strictly monotonic ($G_{k+1} > G_k$); zero drift on status query | All 10 cycles strictly increasing; queries stable | **PASS** |
| `test_ensure_ready_blocks_and_waits_if_stopping` | RS-02 | `ensure_ready` blocks while `Stopping`; spawns replacement cleanly | Blocks until stop completes; 2 spawns total; state = ready_owned | **PASS** |
| `test_stop_generation_guard_preserves_concurrent_epoch` | RS-02 | `stop()` does not overwrite newer generation state | State remains `ReadyOwned`, config = config-v2, gen >= 3 | **PASS** |
| `test_adversarial_ensure_ready_blocks_until_stop_completes` | RS-02 | Blocking duration empirically observed (>= 100ms) | Blocked for ~150ms; final state ready_owned; gen strictly higher | **PASS** |
| `test_adversarial_stop_race_preserves_latest_epoch` | RS-02 | Concurrent `stop()` calls preserve epoch increments | State = stopped, gen >= 3 | **PASS** |
| `test_os_process_handle_job_object_containment` | RS-06 | Windows Job Object assignment with `KILL_ON_JOB_CLOSE` | Win32 `IsProcessInJob` returns true | **PASS** |

---

## 4. Unchallenged Areas

- **RS-03 (Socket Quiescence & Drain)** and **RS-04 (Startup Livelock & Bounded Backoff)**: Assigned to Challenger 2 (`m1_challenger_2`) per division of responsibilities.
- **Windows 7 / legacy Win32 edge cases**: Assumed Windows 10+ environment matching NVDA 2024+ baseline.

---

## 5. Conclusion & Recommendation

The empirical challenge confirms the correctness, safety, and thread synchronization of the RS-01 and RS-02 implementations:
- Generation fencing guarantees strict epoch monotonicity across all failure and exit paths.
- Stopping synchronization guarantees zero orphaned child processes and zero state overwrites.

**Verdict:** **APPROVE**
