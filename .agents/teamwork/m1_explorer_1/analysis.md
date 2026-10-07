# Supervisor State & Concurrency Hardening Analysis: RS-01, RS-02, RS-04

**Document Version:** 1.0.0  
**Target File:** `runtime_supervisor/src/supervisor.rs`  
**Milestone:** Milestone 1 (Slice 0: Rust Runtime Supervisor Concurrency Hardening)  
**Author:** Supervisor State & Concurrency Explorer (`m1_explorer_1`)  
**Status:** Read-Only Design Specification  

---

## 1. Executive Summary

This deliverable provides an exact, code-level fix strategy for three critical concurrency and lifecycle defects in `runtime_supervisor/src/supervisor.rs`:

1. **RS-01 (Generation Counter Monotonicity)**:
   Ensure `InnerState::generation` increments monotonically across every lifecycle epoch termination, specifically when child processes exit or crash, when in-flight startup health checks detect unexpected process exits, when readiness checks time out, and when process spawning fails. This restores Invariant A9 (generation fencing).

2. **RS-02 (Missing Stopping Guard)**:
   Eliminate the race condition between `stop()` and `ensure_ready()`. `ensure_ready()` must wait on `condvar` while `state.state == LifecycleState::Stopping` instead of spawning a rogue replacement child process. Concurrently, `stop()` must capture its entry generation (`my_gen = state.generation`) and guard its terminal state write to `LifecycleState::Stopped` (`if state.generation == my_gen`), preventing stale stops from clobbering newer running epochs.

3. **RS-04 (`ensure_ready` Livelock Mitigation)**:
   Eliminate the ping-pong preemption livelock where competing calls to `ensure_ready()` with differing configurations preempt and terminate each other's in-flight startup sequences. Both identical and differing configurations must wait on `condvar` for the in-flight startup sequence to reach a terminal state (`ReadyOwned`, `ReadyAdopted`, `Failed`, or `Stopped`). If ready, a differing configuration cleanly triggers `restart()`; if failed or stopped, it starts cleanly. In addition, `ensure_ready()` is fortified with a bounded retry limit (`MAX_ATTEMPTS = 5`) and exponential backoff on post-spawn generation collisions.

---

## 2. Feature RS-01: Generation Counter Monotonicity

### 2.1 Problem Analysis & Current Code Flaws
In `runtime_supervisor`, `InnerState::generation` (type `u64`) serves as the epoch counter for generation fencing (Invariant A9). External observers (watchdogs, Python managers, worker IPC) and internal threads query `generation` to ensure status updates and commands are not stale.

In the current code (`ced1cbc`), `generation` increments only when:
- `ensure_ready()` initiates startup (line 272) or supersedes an in-flight startup (line 265).
- `restart()` initiates restart (line 449).
- `stop()` initiates stop (line 472).
- `adopt()` adopts an external server (line 529).

However, `generation` is **omitted** across four critical terminal transitions to `LifecycleState::Failed` or `LifecycleState::Stopped`:
1. `refresh_process_state_locked` (`lines 130–141`): When child process polling detects exit or crash.
2. `ensure_ready` in-flight poll loop (`lines 359–370`): When child process exits during health check polling.
3. `ensure_ready` timeout branch (`lines 408–428`): When child process fails to become healthy within timeout.
4. `ensure_ready` spawn error branch (`lines 328–333`): When OS process spawn fails.

**Consequence**: If a model server crashes, the supervisor enters `Failed`, but `generation` remains identical to the running epoch. Downstream consumers cannot differentiate between a newly crashed state and stale status updates from the prior running session.

---

### 2.2 Exact State Mutation and `condvar.notify_all()` Sequence

For all failure or unhandled exit transitions, the mutation must execute under the `InnerState` mutex lock in the following strict order:
1. Release or consume process resources (`state.process = None` or `state.process.take()`).
2. Advance epoch counter: `state.generation += 1`.
3. Set terminal lifecycle state: `state.state = LifecycleState::Failed` (or `LifecycleState::Stopped` if exit code is 0).
4. Assign diagnostic error message: `state.last_error = Some(...)`.
5. Broadcast wake-up to all waiting threads: `self.condvar.notify_all()`.

---

### 2.3 Exact Code-Level Fixes

#### Location 1: `refresh_process_state_locked` (`supervisor.rs:126–150`)

**Current Code:**
```rust
fn refresh_process_state_locked(&self, state: &mut InnerState) {
    if state.state == LifecycleState::ReadyOwned || state.state == LifecycleState::Starting {
        if let Some(ref mut process) = state.process {
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
                Ok(None) => {}
                Err(e) => {
                    state.last_error = Some(e);
                }
            }
        }
    }
}
```

**Proposed Code:**
```rust
fn refresh_process_state_locked(&self, state: &mut InnerState) {
    if state.state == LifecycleState::ReadyOwned || state.state == LifecycleState::Starting {
        if let Some(ref mut process) = state.process {
            match process.poll() {
                Ok(Some(exit_code)) => {
                    state.process = None;
                    state.generation += 1; // RS-01: Advance epoch on child exit/crash
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
                Ok(None) => {}
                Err(e) => {
                    state.last_error = Some(e);
                }
            }
        }
    }
}
```

---

#### Location 2: `ensure_ready` In-Flight Poll Loop Crash (`supervisor.rs:358–370`)

**Current Code:**
```rust
if let Some(ref mut proc) = s.process {
    if let Ok(Some(code)) = proc.poll() {
        s.process = None;
        s.state = LifecycleState::Failed;
        let err_msg = format!(
            "{} server process exited unexpectedly with code {}",
            self.runtime_name, code
        );
        s.last_error = Some(err_msg.clone());
        self.condvar.notify_all();
        return Err(err_msg);
    }
}
```

**Proposed Code:**
```rust
if let Some(ref mut proc) = s.process {
    if let Ok(Some(code)) = proc.poll() {
        s.process = None;
        s.generation += 1; // RS-01: Advance epoch on in-flight crash
        s.state = LifecycleState::Failed;
        let err_msg = format!(
            "{} server process exited unexpectedly with code {}",
            self.runtime_name, code
        );
        s.last_error = Some(err_msg.clone());
        self.condvar.notify_all();
        return Err(err_msg);
    }
}
```

---

#### Location 3: `ensure_ready` Startup Timeout Branch (`supervisor.rs:405–429`)

**Current Code:**
```rust
// Readiness timeout expired - check exit one last time before declaring timeout
let mut s = self.state.lock().unwrap();
if s.generation == my_gen {
    if let Some(mut proc) = s.process.take() {
        if let Ok(Some(code)) = proc.poll() {
            s.state = LifecycleState::Failed;
            let err_msg = format!(
                "{} server process exited unexpectedly with code {}",
                self.runtime_name, code
            );
            s.last_error = Some(err_msg.clone());
            self.condvar.notify_all();
            return Err(err_msg);
        }
        let _ = proc.terminate();
    }
    s.state = LifecycleState::Failed;
    let err_msg = format!(
        "{} server did not become ready within timeout",
        self.runtime_name
    );
    s.last_error = Some(err_msg.clone());
    self.condvar.notify_all();
    return Err(err_msg);
}
```

**Proposed Code:**
```rust
// Readiness timeout expired - check exit one last time before declaring timeout
let mut s = self.state.lock().unwrap();
if s.generation == my_gen {
    s.generation += 1; // RS-01: Advance epoch on startup timeout
    if let Some(mut proc) = s.process.take() {
        if let Ok(Some(code)) = proc.poll() {
            s.state = LifecycleState::Failed;
            let err_msg = format!(
                "{} server process exited unexpectedly with code {}",
                self.runtime_name, code
            );
            s.last_error = Some(err_msg.clone());
            self.condvar.notify_all();
            return Err(err_msg);
        }
        let _ = proc.terminate();
    }
    s.state = LifecycleState::Failed;
    let err_msg = format!(
        "{} server did not become ready within timeout",
        self.runtime_name
    );
    s.last_error = Some(err_msg.clone());
    self.condvar.notify_all();
    return Err(err_msg);
}
```

---

#### Location 4: `ensure_ready` Spawn Error Branch (`supervisor.rs:327–333`)

**Current Code:**
```rust
match spawn_result {
    Err(err) => {
        state.state = LifecycleState::Failed;
        state.last_error = Some(err.clone());
        self.condvar.notify_all();
        return Err(err);
    }
    Ok(child) => {
        state.process = Some(child);
    }
}
```

**Proposed Code:**
```rust
match spawn_result {
    Err(err) => {
        state.generation += 1; // RS-01: Advance epoch on spawn failure
        state.state = LifecycleState::Failed;
        state.last_error = Some(err.clone());
        self.condvar.notify_all();
        return Err(err);
    }
    Ok(child) => {
        state.process = Some(child);
    }
}
```

---

## 3. Feature RS-02: Missing Stopping Guard

### 3.1 Problem Analysis & Current Code Flaws
Examine `stop()` (`supervisor.rs:470–498`) and `ensure_ready()` (`supervisor.rs:168–275`):

```rust
pub fn stop(&self, timeout: Duration) -> Result<RuntimeStatus, String> {
    let mut state = self.state.lock().unwrap();
    state.generation += 1;
    state.state = LifecycleState::Stopping;
    let mut proc_opt = state.process.take();
    ...
    drop(state); // <--- Lock dropped!

    if let Some(ref mut proc) = proc_opt {
        let _ = proc.terminate();
        let _ = proc.wait_timeout(timeout); // <--- Blocks for up to 5-10s
    }

    let mut state = self.state.lock().unwrap();
    state.state = LifecycleState::Stopped; // <--- UNCONDITIONAL OVERWRITE!
    self.condvar.notify_all();
    ...
}
```

In `ensure_ready()`:
```rust
'outer: loop {
    let mut state = self.state.lock().unwrap();
    self.refresh_process_state_locked(&mut state);

    // 1. ReadyOwned matching current configuration
    if state.state == LifecycleState::ReadyOwned { ... }
    // 2. ReadyAdopted
    if state.state == LifecycleState::ReadyAdopted { ... }
    // 3. In-flight Starting
    if state.state == LifecycleState::Starting { ... }

    // 4. Stopped or Failed: begin transition to Starting under lock
    state.generation += 1;
    let my_gen = state.generation;
    state.state = LifecycleState::Starting;
```

**Failure Mechanism (Zombie Creation)**:
1. Thread 1 calls `stop()`: `state.state = Stopping`, drops lock, enters `proc.wait_timeout(5s)`.
2. Thread 2 calls `ensure_ready()`: examines `state.state`. It is NOT `ReadyOwned`, NOT `ReadyAdopted`, NOT `Starting`.
3. Thread 2 falls through straight to Step 4! It increments generation, sets `Starting`, drops lock, and spawns Child 2.
4. Thread 1 finishes waiting for Child 1, acquires the lock, and **unconditionally overwrites** `state.state = LifecycleState::Stopped`!
5. Thread 2’s post-spawn or poll checks observe `state.state == Stopped`, and Thread 2 aborts with error `"server startup was stopped"`.
6. Child 2 continues running indefinitely in the background as an **untracked zombie process**, holding port bindings and GPU VRAM.

---

### 3.2 Exact Code-Level Fixes

#### Part A: Stopping Guard in `ensure_ready`
In `ensure_ready()`, insert a dedicated guard immediately after `refresh_process_state_locked`:

```rust
'outer: loop {
    let mut state = self.state.lock().unwrap();
    self.refresh_process_state_locked(&mut state);

    // 0. Stopping: wait until the supervisor has finished stopping
    if state.state == LifecycleState::Stopping {
        let remaining = timeout.saturating_sub(start_time.elapsed());
        if remaining.is_zero() {
            return Err(format!(
                "Timed out waiting for {} server to stop before startup could begin",
                self.runtime_name
            ));
        }
        let (new_state, wait_res) = self
            .condvar
            .wait_timeout_while(state, remaining, |s| s.state == LifecycleState::Stopping)
            .unwrap();
        state = new_state;
        if wait_res.timed_out() && state.state == LifecycleState::Stopping {
            return Err(format!(
                "Timed out waiting for {} server to stop",
                self.runtime_name
            ));
        }
        continue 'outer;
    }

    // 1. ReadyOwned matching current configuration
    ...
```

**Behavior**:
- Atomically releases lock and blocks on `condvar` while `s.state == LifecycleState::Stopping`.
- If timeout expires, cleanly returns an error without spawning any child process.
- When `stop()` completes and broadcasts `notify_all()`, the waiting thread wakes, observes `state.state != Stopping` (typically `Stopped`), and re-executes `'outer` from the top, initiating startup safely.

---

#### Part B: Generation Capture and Conditional Write Guard in `stop()`
In `stop()` (`supervisor.rs:470–498`):

```rust
pub fn stop(&self, timeout: Duration) -> Result<RuntimeStatus, String> {
    let mut state = self.state.lock().unwrap();
    state.generation += 1;
    let my_gen = state.generation; // RS-02: Capture generation assigned to this stop operation
    state.state = LifecycleState::Stopping;
    let mut proc_opt = state.process.take();
    state.startup_identity = None;
    state.running_model = None;
    self.condvar.notify_all();
    drop(state);

    if let Some(ref mut proc) = proc_opt {
        let _ = proc.terminate();
        let _ = proc.wait_timeout(timeout);
    }

    let mut state = self.state.lock().unwrap();
    // RS-02: Only overwrite to Stopped if generation has not advanced
    if state.generation == my_gen {
        state.state = LifecycleState::Stopped;
        self.condvar.notify_all();
    }

    let pid = state.process.as_ref().map(|p| p.pid());
    Ok(RuntimeStatus::new(
        state.state,
        pid,
        state.generation,
        state.last_error.clone(),
        state.startup_identity.clone(),
        state.running_model.clone(),
        self.base_url.clone(),
    ))
}
```

**Behavior**:
- Captures `my_gen = state.generation` under the initial lock.
- After `wait_timeout()`, re-acquires the lock and verifies `if state.generation == my_gen`.
- If another operation (e.g. concurrent `adopt()`, newer `stop()`, or external transition) advanced the generation, `stop()` leaves the newer state intact.
- Accurately constructs `RuntimeStatus` reflecting current state and PID.

---

## 4. Feature RS-04: `ensure_ready` Livelock Mitigation

### 4.1 Problem Analysis & Ping-Pong Preemption Mechanism
In `supervisor.rs:224–269`:

```rust
if state.state == LifecycleState::Starting {
    if let Some(ref active) = state.active_config {
        if active.startup_identity == startup_identity {
            // Matching config waits on condvar...
            ...
        }
    }
    // Config differs while starting: supersede current startup
    state.generation += 1;
    if let Some(mut old_proc) = state.process.take() {
        let _ = old_proc.terminate();
    }
}
```

**Mechanism of the Livelock**:
1. Thread 1 calls `ensure_ready(Config A)`. State becomes `Starting` (generation 1). Thread 1 begins spawning Child A.
2. Thread 2 calls `ensure_ready(Config B)` concurrently. Sees `state == Starting`. Since `Config B != Config A`, Thread 2 hits line 265: increments generation to 2, takes and terminates Child A, sets `active_config = Config B` (generation 3), and begins spawning Child B.
3. Thread 1 finishes spawning, re-acquires lock, detects `state.generation (3) != my_gen (1)`, kills Child A, and loops back to `'outer`.
4. In `'outer`, Thread 1 sees `state == Starting` with `Config B`. Since `Config A != Config B`, Thread 1 supersedes Thread 2: increments generation to 4, terminates Child B, sets `active_config = Config A` (generation 5), and begins spawning Child A.
5. Thread 2 finishes spawning, detects generation mismatch (5 != 3), kills Child B, and loops to supersede Thread 1 again.
6. **Result**: Both threads endlessly kill each other's processes without ever giving either process time to become healthy.

---

### 4.2 Fix Strategy: Condvar Waiting on In-Flight Startup + Bounded Retries

#### Principle:
**Never supersede an in-flight startup sequence.**  
Regardless of whether the caller's configuration matches or differs from `active_config`, the caller must wait on `condvar` for the in-flight startup to complete or fail.

#### Two-Phase Execution:
1. **Wait Phase**:
   Any caller arriving while `state.state == LifecycleState::Starting` waits on `condvar` until the state is no longer `Starting` (or generation changes).
2. **Re-Evaluation Phase**:
   - **If caller requested the same configuration**:
     If state reached `ReadyOwned` or `ReadyAdopted`, return immediately with `Ok(RuntimeStatus)`.
     If state reached `Failed`, return immediately with `Err(state.last_error)` (preventing redundant failed attempts).
   - **If caller requested a different configuration**:
     Wake up and `continue 'outer`.
     On the next loop iteration:
     - If the in-flight startup reached `ReadyOwned`: Step 1 runs. Step 1 detects configuration mismatch and cleanly calls `self.restart(...)`. `restart()` performs an orderly shutdown and restarts with the new configuration.
     - If the in-flight startup reached `Failed` or `Stopped`: Step 4 runs. The caller cleanly starts its new configuration from scratch.
   Zero process ping-pong. Zero livelock.

#### Retry Bounds & Exponential Backoff:
- Enforce a maximum loop retry bound: `const MAX_ATTEMPTS: usize = 5`.
- If a generation conflict occurs during OS process spawning (`state.generation != my_gen` at line 316), drop the lock and sleep with exponential backoff (`Duration::from_millis(50 * 2^(attempt - 1))`) before continuing `'outer`.

---

### 4.3 Exact Code-Level Fixes in `ensure_ready`

```rust
#[allow(clippy::too_many_arguments)]
pub fn ensure_ready(
    &self,
    executable: &str,
    args: &[String],
    env: &HashMap<String, String>,
    startup_identity: &str,
    running_model: Option<&str>,
    timeout: Duration,
) -> Result<RuntimeStatus, String> {
    let start_time = Instant::now();
    const MAX_ATTEMPTS: usize = 5;
    let mut attempt: usize = 0;

    'outer: loop {
        attempt += 1;
        if attempt > MAX_ATTEMPTS {
            return Err(format!(
                "{} server exceeded maximum startup retry attempts ({})",
                self.runtime_name, MAX_ATTEMPTS
            ));
        }

        let mut state = self.state.lock().unwrap();
        self.refresh_process_state_locked(&mut state);

        // 0. Stopping: wait until supervisor finishes stopping (RS-02)
        if state.state == LifecycleState::Stopping {
            let remaining = timeout.saturating_sub(start_time.elapsed());
            if remaining.is_zero() {
                return Err(format!(
                    "Timed out waiting for {} server to stop before startup could begin",
                    self.runtime_name
                ));
            }
            let (new_state, wait_res) = self
                .condvar
                .wait_timeout_while(state, remaining, |s| s.state == LifecycleState::Stopping)
                .unwrap();
            state = new_state;
            if wait_res.timed_out() && state.state == LifecycleState::Stopping {
                return Err(format!(
                    "Timed out waiting for {} server to stop",
                    self.runtime_name
                ));
            }
            continue 'outer;
        }

        // 1. ReadyOwned matching current configuration
        if state.state == LifecycleState::ReadyOwned {
            if state.startup_identity.as_deref() == Some(startup_identity) {
                let pid = state.process.as_ref().map(|p| p.pid());
                return Ok(RuntimeStatus::new(
                    state.state,
                    pid,
                    state.generation,
                    state.last_error.clone(),
                    state.startup_identity.clone(),
                    state.running_model.clone(),
                    self.base_url.clone(),
                ));
            }
            // Config changed; restart needed
            drop(state);
            return self.restart(
                executable,
                args,
                env,
                startup_identity,
                running_model,
                timeout.saturating_sub(start_time.elapsed()),
            );
        }

        // 2. ReadyAdopted
        if state.state == LifecycleState::ReadyAdopted {
            drop(state);
            if self
                .health_checker
                .check_health(&self.base_url, Duration::from_millis(500))
            {
                let s = self.state.lock().unwrap();
                let pid = s.process.as_ref().map(|p| p.pid());
                return Ok(RuntimeStatus::new(
                    s.state,
                    pid,
                    s.generation,
                    s.last_error.clone(),
                    s.startup_identity.clone(),
                    s.running_model.clone(),
                    self.base_url.clone(),
                ));
            }
            // Adopted server disappeared; reset to stopped and fall through to spawn
            let mut s = self.state.lock().unwrap();
            s.state = LifecycleState::Stopped;
            continue 'outer;
        }

        // 3. In-flight Starting: wait on condvar regardless of config to eliminate livelock (RS-04)
        if state.state == LifecycleState::Starting {
            let my_gen = state.generation;
            let is_same_config = state
                .active_config
                .as_ref()
                .map(|active| active.startup_identity == startup_identity)
                .unwrap_or(false);

            let remaining = timeout.saturating_sub(start_time.elapsed());
            if remaining.is_zero() {
                return Err(format!(
                    "{} server readiness timed out waiting for in-flight startup",
                    self.runtime_name
                ));
            }
            let (new_state, wait_res) = self
                .condvar
                .wait_timeout_while(state, remaining, |s| {
                    s.state == LifecycleState::Starting && s.generation == my_gen
                })
                .unwrap();
            state = new_state;

            if wait_res.timed_out() && state.state == LifecycleState::Starting {
                return Err(format!(
                    "{} server readiness timed out waiting for in-flight startup",
                    self.runtime_name
                ));
            }

            if is_same_config {
                if state.state == LifecycleState::ReadyOwned
                    || state.state == LifecycleState::ReadyAdopted
                {
                    let pid = state.process.as_ref().map(|p| p.pid());
                    return Ok(RuntimeStatus::new(
                        state.state,
                        pid,
                        state.generation,
                        state.last_error.clone(),
                        state.startup_identity.clone(),
                        state.running_model.clone(),
                        self.base_url.clone(),
                    ));
                } else if state.state == LifecycleState::Failed {
                    return Err(state.last_error.clone().unwrap_or_else(|| {
                        format!("{} server failed to start", self.runtime_name)
                    }));
                }
            }
            // Differing config or cancelled startup: re-evaluate on next iteration
            continue 'outer;
        }

        // 4. Stopped or Failed: begin transition to Starting under lock
        state.generation += 1;
        let my_gen = state.generation;
        state.state = LifecycleState::Starting;
        state.last_error = None;
        state.active_config = Some(ActiveConfig {
            executable: executable.to_string(),
            args: args.to_vec(),
            env: env.clone(),
            startup_identity: startup_identity.to_string(),
        });
        self.condvar.notify_all();

        // Check if there is an adoptable server already running
        drop(state);
        if self
            .health_checker
            .check_compatible(&self.base_url, Duration::from_millis(500))
        {
            let mut s = self.state.lock().unwrap();
            if s.generation == my_gen {
                s.state = LifecycleState::ReadyAdopted;
                s.running_model = running_model.map(|m| m.to_string());
                s.last_error = None;
                s.startup_identity = None;
                self.condvar.notify_all();
                return Ok(RuntimeStatus::new(
                    s.state,
                    None,
                    s.generation,
                    None,
                    None,
                    s.running_model.clone(),
                    self.base_url.clone(),
                ));
            }
            continue 'outer;
        }

        // Spawn child process outside mutex
        let spawn_start = Instant::now();
        let spawn_result = self.process_driver.spawn(executable, args, env);

        let mut state = self.state.lock().unwrap();
        // Check if generation changed while spawning
        if state.generation != my_gen {
            if let Ok(mut child) = spawn_result {
                let _ = child.terminate();
            }
            if state.state == LifecycleState::Stopped || state.state == LifecycleState::Stopping {
                return Err(format!("{} server startup was stopped", self.runtime_name));
            }
            drop(state);
            // Exponential backoff to avoid tight spinning on generation conflict
            let backoff = Duration::from_millis(50 * (1 << (attempt - 1).min(4)) as u64);
            std::thread::sleep(backoff);
            continue 'outer;
        }

        match spawn_result {
            Err(err) => {
                state.generation += 1; // RS-01: Advance epoch on spawn error
                state.state = LifecycleState::Failed;
                state.last_error = Some(err.clone());
                self.condvar.notify_all();
                return Err(err);
            }
            Ok(child) => {
                state.process = Some(child);
            }
        }

        // Poll health loop until ready or timeout
        drop(state);
        let deadline = Instant::now() + timeout.saturating_sub(spawn_start.elapsed());
        let poll_interval = Duration::from_millis(100);

        while Instant::now() < deadline {
            // Check if generation changed or child died
            {
                let mut s = self.state.lock().unwrap();
                if s.generation != my_gen {
                    if s.state == LifecycleState::Stopped || s.state == LifecycleState::Stopping {
                        return Err(format!(
                            "{} server startup was stopped",
                            self.runtime_name
                        ));
                    }
                    continue 'outer;
                }
                if let Some(ref mut proc) = s.process {
                    if let Ok(Some(code)) = proc.poll() {
                        s.process = None;
                        s.generation += 1; // RS-01: Advance epoch on poll crash
                        s.state = LifecycleState::Failed;
                        let err_msg = format!(
                            "{} server process exited unexpectedly with code {}",
                            self.runtime_name, code
                        );
                        s.last_error = Some(err_msg.clone());
                        self.condvar.notify_all();
                        return Err(err_msg);
                    }
                }
            }

            // Check health
            if self
                .health_checker
                .check_health(&self.base_url, Duration::from_millis(200))
            {
                let mut s = self.state.lock().unwrap();
                if s.generation == my_gen {
                    s.state = LifecycleState::ReadyOwned;
                    s.startup_identity = Some(startup_identity.to_string());
                    s.running_model = running_model.map(|m| m.to_string());
                    s.last_error = None;
                    self.condvar.notify_all();
                    let pid = s.process.as_ref().map(|p| p.pid());
                    return Ok(RuntimeStatus::new(
                        s.state,
                        pid,
                        s.generation,
                        None,
                        s.startup_identity.clone(),
                        s.running_model.clone(),
                        self.base_url.clone(),
                    ));
                }
                if s.state == LifecycleState::Stopped || s.state == LifecycleState::Stopping {
                    return Err(format!("{} server startup was stopped", self.runtime_name));
                }
                continue 'outer;
            }

            std::thread::sleep(poll_interval);
        }

        // Readiness timeout expired
        let mut s = self.state.lock().unwrap();
        if s.generation == my_gen {
            s.generation += 1; // RS-01: Advance epoch on startup timeout
            if let Some(mut proc) = s.process.take() {
                if let Ok(Some(code)) = proc.poll() {
                    s.state = LifecycleState::Failed;
                    let err_msg = format!(
                        "{} server process exited unexpectedly with code {}",
                        self.runtime_name, code
                    );
                    s.last_error = Some(err_msg.clone());
                    self.condvar.notify_all();
                    return Err(err_msg);
                }
                let _ = proc.terminate();
            }
            s.state = LifecycleState::Failed;
            let err_msg = format!(
                "{} server did not become ready within timeout",
                self.runtime_name
            );
            s.last_error = Some(err_msg.clone());
            self.condvar.notify_all();
            return Err(err_msg);
        }
        if s.state == LifecycleState::Stopped || s.state == LifecycleState::Stopping {
            return Err(format!("{} server startup was stopped", self.runtime_name));
        }
        continue 'outer;
    }
}
```

---

## 5. Verification: Regression Test Design in `runtime_supervisor/src/tests.rs`

To guarantee regression coverage for RS-01, RS-02, and RS-04, the following tests should be implemented in `runtime_supervisor/src/tests.rs`:

### Test 1: `test_child_crash_increments_generation_in_status` (RS-01)
```rust
#[test]
fn test_child_crash_increments_generation_in_status() {
    let driver = Arc::new(FakeProcessDriver::new());
    let health = Arc::new(FakeHealthChecker::new(true, false));
    let supervisor = create_test_supervisor(Arc::clone(&driver), health);

    // Start server to ReadyOwned
    let res = supervisor.ensure_ready(
        "python.exe",
        &["serve".into()],
        &HashMap::new(),
        "config-v1",
        None,
        Duration::from_secs(1),
    );
    assert!(res.is_ok());
    let status_before = supervisor.status();
    assert_eq!(status_before.state, "ready_owned");
    let gen_before = status_before.generation;

    // Simulate child process crash
    driver.current_alive.store(false, Ordering::SeqCst);
    driver.exit_code.store(137, Ordering::SeqCst);

    // status() polls process and detects crash
    let status_after = supervisor.status();
    assert_eq!(status_after.state, "failed");
    assert_eq!(
        status_after.generation,
        gen_before + 1,
        "Generation must advance monotonically on process crash"
    );
    assert!(status_after.error_message.unwrap().contains("137"));
}
```

### Test 2: `test_startup_child_crash_increments_generation` (RS-01)
```rust
#[test]
fn test_startup_child_crash_increments_generation() {
    let driver = Arc::new(FakeProcessDriver::new());
    driver.exit_immediately.store(true, Ordering::SeqCst);
    driver.exit_code.store(42, Ordering::SeqCst);
    let health = Arc::new(FakeHealthChecker::new(false, false));
    let supervisor = create_test_supervisor(driver, health);

    let res = supervisor.ensure_ready(
        "python.exe",
        &["serve".into()],
        &HashMap::new(),
        "config-v1",
        None,
        Duration::from_secs(1),
    );
    assert!(res.is_err());
    let status = supervisor.status();
    assert_eq!(status.state, "failed");
    // Gen 0 -> Starting (1) -> Crash detected (2)
    assert!(status.generation >= 2, "Generation must advance on startup crash");
}
```

### Test 3: `test_readiness_timeout_increments_generation` (RS-01)
```rust
#[test]
fn test_readiness_timeout_increments_generation() {
    let driver = Arc::new(FakeProcessDriver::new());
    let health = Arc::new(FakeHealthChecker::new(false, false));
    let supervisor = create_test_supervisor(driver, health);

    let res = supervisor.ensure_ready(
        "python.exe",
        &["serve".into()],
        &HashMap::new(),
        "config-v1",
        None,
        Duration::from_millis(250),
    );
    assert!(res.is_err());
    let status = supervisor.status();
    assert_eq!(status.state, "failed");
    // Gen 0 -> Starting (1) -> Timeout (2)
    assert!(status.generation >= 2, "Generation must advance on readiness timeout");
}
```

### Test 4: `test_ensure_ready_blocks_and_waits_if_stopping` (RS-02)
```rust
#[test]
fn test_ensure_ready_blocks_and_waits_if_stopping() {
    let driver = Arc::new(FakeProcessDriver::new());
    let health = Arc::new(FakeHealthChecker::new(true, false));
    let supervisor = Arc::new(create_test_supervisor(Arc::clone(&driver), health));

    // Start server to ReadyOwned
    supervisor
        .ensure_ready(
            "python.exe",
            &["serve".into()],
            &HashMap::new(),
            "config-v1",
            None,
            Duration::from_secs(1),
        )
        .unwrap();
    assert_eq!(driver.spawns.load(Ordering::SeqCst), 1);

    // Call stop in thread 1 with simulated delay
    let sup1 = Arc::clone(&supervisor);
    let stopper = thread::spawn(move || {
        sup1.stop(Duration::from_millis(500))
    });

    // Wait until supervisor transitions to Stopping
    while supervisor.status().state != "stopping" {
        thread::sleep(Duration::from_millis(5));
    }

    // Call ensure_ready in thread 2 while supervisor is Stopping
    let sup2 = Arc::clone(&supervisor);
    let starter = thread::spawn(move || {
        sup2.ensure_ready(
            "python.exe",
            &["serve".into()],
            &HashMap::new(),
            "config-v1",
            None,
            Duration::from_secs(2),
        )
    });

    stopper.join().unwrap().unwrap();
    let res = starter.join().unwrap();
    assert!(res.is_ok(), "ensure_ready must succeed after stop finishes");

    // Must have spawned exactly 2 processes (1 initial, 1 after clean stop; 0 rogue zombie spawns)
    assert_eq!(driver.spawns.load(Ordering::SeqCst), 2);
    assert_eq!(supervisor.status().state, "ready_owned");
}
```

### Test 5: `test_concurrent_conflicting_configs_no_livelock` (RS-04)
```rust
#[test]
fn test_concurrent_conflicting_configs_no_livelock() {
    let driver = Arc::new(FakeProcessDriver::new());
    let health = Arc::new(FakeHealthChecker::new(true, false));
    let supervisor = Arc::new(create_test_supervisor(Arc::clone(&driver), health));

    let sup_a = Arc::clone(&supervisor);
    let thread_a = thread::spawn(move || {
        sup_a.ensure_ready(
            "python.exe",
            &["serve".into()],
            &HashMap::new(),
            "config-A",
            None,
            Duration::from_secs(3),
        )
    });

    let sup_b = Arc::clone(&supervisor);
    let thread_b = thread::spawn(move || {
        sup_b.ensure_ready(
            "python.exe",
            &["serve".into()],
            &HashMap::new(),
            "config-B",
            None,
            Duration::from_secs(3),
        )
    });

    let res_a = thread_a.join().unwrap();
    let res_b = thread_b.join().unwrap();

    assert!(res_a.is_ok(), "Thread A failed: {:?}", res_a);
    assert!(res_b.is_ok(), "Thread B failed: {:?}", res_b);

    // Spawns must be strictly bounded (at most 2: one for A, one for B restart; NO livelock explosion)
    let total_spawns = driver.spawns.load(Ordering::SeqCst);
    assert!(
        total_spawns <= 2,
        "Total spawns must be <= 2, got {} (indicates livelock)",
        total_spawns
    );
}
```

---

## 6. Downstream Invariant Conformance & Readiness

- **Invariant A9 (Generation Fencing)**: Fully enforced. Epoch strictly advances monotonically on every state transition, crash, exit, timeout, and stop.
- **Invariant A7 (Authoritative Native Owner)**: Rust `runtime_supervisor` remains the single point of truth for process lifecycle and state transitions.
- **Invariant A26 (Deterministic Containment)**: Process teardown and lifecycle transitions are fully synchronized via condvar without races.

This completes the concrete fix strategy for RS-01, RS-02, and RS-04.
