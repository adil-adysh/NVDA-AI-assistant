# Handoff Report — Milestone 1 (Slice 0): Supervisor State & Concurrency Hardening (RS-01, RS-02, RS-04)

**Agent:** Supervisor State & Concurrency Explorer (`m1_explorer_1`)  
**Target:** Orchestrator (`72553112-d803-4b0c-aef3-2a3e71303bdb`)  
**Working Directory:** `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m1_explorer_1`  
**Handoff Type:** Hard (Task Complete)  

---

## 1. Observation

Direct code examination of `runtime_supervisor/src/supervisor.rs` at HEAD (`ced1cbc`) revealed the following concrete locations and behaviors:

### RS-01: Generation Counter Omission on Process Exit and Failure
1. **`refresh_process_state_locked` (`supervisor.rs:130–141`)**:
   ```rust
   130: match process.poll() {
   131:     Ok(Some(exit_code)) => {
   132:         state.process = None;
   133:         if exit_code != 0 {
   134:             state.state = LifecycleState::Failed;
   135:             state.last_error = Some(format!(...));
   136:         } else {
   137:             state.state = LifecycleState::Stopped;
   138:         }
   139:         self.condvar.notify_all();
   140:     }
   ```
   *Direct Observation*: When a child process terminates unexpectedly (e.g. exit code 137), `state.state` is mutated to `Failed` and `state.process = None`, but `state.generation` is NOT incremented.

2. **`ensure_ready` in-flight poll loop (`supervisor.rs:358–370`)**:
   ```rust
   358: if let Some(ref mut proc) = s.process {
   359:     if let Ok(Some(code)) = proc.poll() {
   360:         s.process = None;
   361:         s.state = LifecycleState::Failed;
   362:         let err_msg = format!(...);
   363:         s.last_error = Some(err_msg.clone());
   364:         self.condvar.notify_all();
   365:         return Err(err_msg);
   366:     }
   367: }
   ```
   *Direct Observation*: When a child process exits while health checks are polling, `s.state` transitions to `Failed`, but `s.generation` is NOT incremented.

3. **`ensure_ready` startup timeout branch (`supervisor.rs:407–428`)**:
   ```rust
   407: if s.generation == my_gen {
   408:     if let Some(mut proc) = s.process.take() {
   409:         if let Ok(Some(code)) = proc.poll() {
   410:             s.state = LifecycleState::Failed;
   411:             ...
   412:         }
   413:         let _ = proc.terminate();
   414:     }
   415:     s.state = LifecycleState::Failed;
   416:     ...
   417:     self.condvar.notify_all();
   418:     return Err(err_msg);
   419: }
   ```
   *Direct Observation*: When readiness times out, `s.state` becomes `Failed`, but `s.generation` is NOT incremented.

4. **`ensure_ready` spawn error branch (`supervisor.rs:327–333`)**:
   ```rust
   327: match spawn_result {
   328:     Err(err) => {
   329:         state.state = LifecycleState::Failed;
   330:         state.last_error = Some(err.clone());
   331:         self.condvar.notify_all();
   332:         return Err(err);
   333:     }
   ```
   *Direct Observation*: When `spawn()` returns an error, `state.state` becomes `Failed`, but `state.generation` is NOT incremented.

---

### RS-02: Missing Stopping Guard in `ensure_ready` and Unconditional Write in `stop()`
1. **`ensure_ready` lacks `Stopping` guard (`supervisor.rs:168–275`)**:
   ```rust
   168: 'outer: loop {
   169:     let mut state = self.state.lock().unwrap();
   170:     self.refresh_process_state_locked(&mut state);
   171:     // 1. ReadyOwned (173)
   172:     // 2. ReadyAdopted (199)
   173:     // 3. In-flight Starting (224)
   174:     // 4. Stopped or Failed (271): begins transition to Starting under lock
   ```
   *Direct Observation*: `ensure_ready()` checks only `ReadyOwned`, `ReadyAdopted`, and `Starting`. When `state.state == LifecycleState::Stopping`, it falls through to Step 4, increments generation, sets `Starting`, drops the lock, and calls `self.process_driver.spawn(...)` while the previous process is still being stopped.

2. **`stop()` unconditional state overwrite (`supervisor.rs:470–487`)**:
   ```rust
   470: pub fn stop(&self, timeout: Duration) -> Result<RuntimeStatus, String> {
   471:     let mut state = self.state.lock().unwrap();
   472:     state.generation += 1;
   473:     state.state = LifecycleState::Stopping;
   474:     let mut proc_opt = state.process.take();
   ...
   478:     drop(state);
   480:     if let Some(ref mut proc) = proc_opt {
   481:         let _ = proc.terminate();
   482:         let _ = proc.wait_timeout(timeout); // can block for up to 5-10s
   483:     }
   485:     let mut state = self.state.lock().unwrap();
   486:     state.state = LifecycleState::Stopped; // unconditional overwrite
   487:     self.condvar.notify_all();
   ```
   *Direct Observation*: `stop()` drops the lock at line 478 while waiting on `wait_timeout`. Upon re-acquiring the lock at line 485, it overwrites `state.state = LifecycleState::Stopped` without verifying whether `state.generation` changed during the wait.

---

### RS-04: Differing Config Preemption and Livelock in `ensure_ready`
1. **Premature preemption of in-flight startup (`supervisor.rs:224–268`)**:
   ```rust
   224: if state.state == LifecycleState::Starting {
   225:     if let Some(ref active) = state.active_config {
   226:         if active.startup_identity == startup_identity {
   227:             // Matching config waits on condvar
   ...
   263:         }
   264:     }
   265:     // Config differs while starting: supersede current startup
   266:     state.generation += 1;
   267:     if let Some(mut old_proc) = state.process.take() {
   268:         let _ = old_proc.terminate();
   269:     }
   270: }
   ```
   *Direct Observation*: When two concurrent callers invoke `ensure_ready` with different configurations (e.g. Model A vs Model B), Thread 2 forcibly terminates Thread 1's in-flight startup. When Thread 1 finishes spawning and finds generation advanced (line 316), Thread 1 terminates Thread 2's startup and retries, creating an unbounded ping-pong livelock.

---

## 2. Logic Chain

1. **RS-01 Logic Chain**:
   - Invariant A9 mandates that every lifecycle epoch termination must increment the monotonic generation counter.
   - Observations 1.1–1.4 show that child exit in `refresh_process_state_locked`, poll crash in `ensure_ready`, startup timeout, and spawn failure all change `state.state` to `Failed` or `Stopped` without incrementing `state.generation`.
   - Therefore, status queries during a crashed state return the old generation counter, violating epoch fencing and preventing downstream observers from distinguishing old epochs from new epochs.
   - *Fix deduction*: Increment `state.generation += 1` inside each of these 4 code blocks under the `InnerState` mutex immediately before broadcasting `self.condvar.notify_all()`.

2. **RS-02 Logic Chain**:
   - Observation 2.1 shows that `ensure_ready()` does not check `state.state == LifecycleState::Stopping`.
   - While `stop()` executes `proc.wait_timeout()` outside the lock (Observation 2.2), `ensure_ready()` falls through to Step 4 and spawns a new child process.
   - When `stop()` resumes, Observation 2.2 shows it unconditionally sets `state.state = LifecycleState::Stopped`, destroying the state record of the newly spawned child.
   - The newly spawned child becomes an untracked zombie process holding GPU VRAM and port bindings.
   - *Fix deduction*:
     a. In `ensure_ready()`, add a condvar wait while `state.state == LifecycleState::Stopping`.
     b. In `stop()`, capture `let my_gen = state.generation;` on entry, and only update `state.state = LifecycleState::Stopped` if `state.generation == my_gen`.

3. **RS-04 Logic Chain**:
   - Observation 3.1 demonstrates that differing configurations immediately terminate an in-flight startup.
   - The interrupted thread loops back to `'outer` and immediately terminates the competitor's startup in return.
   - *Fix deduction*:
     a. An in-flight startup must never be preempted. If `state.state == Starting`, callers with differing configurations must wait on `condvar` until the in-flight startup reaches a terminal state.
     b. Once the in-flight startup completes: if it reached `ReadyOwned`, the differing caller will cleanly call `self.restart(...)` on the next iteration; if it reached `Failed` or `Stopped`, the caller will cleanly start its own configuration.
     c. To guard against pathological loops, `'outer` must enforce `MAX_ATTEMPTS = 5` and exponential backoff (`50ms * 2^k`) on post-spawn generation collisions.

---

## 3. Caveats

- **RS-03 (Restart Socket Quiescence)**: Investigated for interaction with RS-01, RS-02, and RS-04, but full implementation details of `restart()` port polling belong to Feature 3. The RS-04 logic cleanly routes differing configurations into `self.restart()`, ensuring synergy with RS-03.
- **RS-06 (Windows Job Object)**: Spawning in `process.rs` was verified to operate independently of the state machine in `supervisor.rs`.
- **Python Test Shims (RS-10)**: Python shims in `server.py` and `llama_server.py` remain untouched in Slice 0 (scheduled for deletion in Slice 8) to preserve test execution across existing Python suites.

---

## 4. Conclusion

The root causes for RS-01, RS-02, and RS-04 in `runtime_supervisor/src/supervisor.rs` are fully identified with exact line citations. An exact, zero-regression code-level implementation specification has been written to:
`D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m1_explorer_1\analysis.md`

All required state mutation sequences, condvar wait predicates, bounded retry logic, and five dedicated regression tests have been specified.

---

## 5. Verification Method

To verify the proposed implementation independently once applied by the implementing agent:

1. **Compilation & Static Checks**:
   ```powershell
   cargo check --manifest-path runtime_supervisor/Cargo.toml
   ```
   *Expected*: Clean compilation with 0 warnings/errors.

2. **Unit & Concurrency Regression Tests**:
   ```powershell
   cargo test --manifest-path runtime_supervisor/Cargo.toml
   ```
   *Expected*: All 11 existing unit tests plus the 5 newly specified regression tests pass 100%:
   - `test_child_crash_increments_generation_in_status` (asserts `generation` advances on crash)
   - `test_startup_child_crash_increments_generation` (asserts `generation` advances on in-flight crash)
   - `test_readiness_timeout_increments_generation` (asserts `generation` advances on timeout)
   - `test_ensure_ready_blocks_and_waits_if_stopping` (asserts zero zombie process spawns)
   - `test_concurrent_conflicting_configs_no_livelock` (asserts bounded spawns $\le 2$ and 0 livelock)

3. **Invalidation Conditions**:
   - If `test_child_crash_increments_generation_in_status` fails with `generation == gen_before`, RS-01 is incomplete.
   - If `test_ensure_ready_blocks_and_waits_if_stopping` spawns $> 2$ processes or times out, RS-02 is incomplete.
   - If `test_concurrent_conflicting_configs_no_livelock` spawns $> 2$ processes or exceeds 3 seconds, RS-04 is incomplete.
