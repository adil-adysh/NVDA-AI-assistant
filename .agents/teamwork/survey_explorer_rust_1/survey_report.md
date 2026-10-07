# Rust Runtime Supervisor Survey Report — Slice 0

**Document Version:** 1.0.0 (Authoritative Survey Deliverable)  
**Date:** 2026-10-04  
**Investigator:** Rust Runtime Supervisor Explorer (`survey_explorer_rust_1`)  
**Target Repository:** `adil-adysh/NVDA-AI-assistant`  
**Working Directory:** `D:\nvda-addons\NVDA-AI-assistant`  
**Scope:** Slice 0 — Rust Runtime Supervisor Concurrency Hardening & Contract Verification (RS-01, RS-02, RS-03, RS-04, RS-06, RS-10, and Test Suite)

---

## 1. Executive Summary

This report delivers a comprehensive, code-level survey and architectural audit of `runtime_supervisor` (and its interactions with the Python add-on) for Slice 0. All findings are verified against the current repository state (`ced1cbc` and ancestors), the master architecture deliverable (`architecture_deliverable.md`), and the baseline test suite.

### Key Audit Findings at a Glance
1. **RS-01 (Generation Counter Omission — CONFIRMED, BLOCKER)**: Verified across `supervisor.rs:130–141`, `358–370`, and `408–428`. The monotonic generation counter (`state.generation`) fails to increment when a child process exits unexpectedly, crashes, or times out during readiness checks. This violates Invariant A9 and invalidates epoch-based generation fencing.
2. **RS-02 (Missing Stopping Guard — CONFIRMED, BLOCKER)**: Verified across `supervisor.rs:168–275` and `485–487`. `ensure_ready()` lacks a guard for `LifecycleState::Stopping`. A concurrent startup while `stop()` awaits process exit spawns a new process, which is subsequently overwritten to `Stopped` by `stop()`, creating orphaned zombie processes holding GPU memory and port bindings.
3. **RS-03 (Socket Collision on Restart — CONFIRMED, BLOCKER)**: Verified in `supervisor.rs:448–467`. `restart()` issues `proc.terminate()` without awaiting exit (`proc.wait()` / `wait_timeout()`) or verifying port release before calling `ensure_ready()`. This creates a severe race condition: either the dying server is mistakenly re-adopted as `ReadyAdopted`, or the newly spawned process crashes with `WSAEADDRINUSE` (10048).
4. **RS-04 (`ensure_ready` Livelock — CONFIRMED, BLOCKER)**: Verified in `supervisor.rs:223–269` and `314–325`. When two threads call `ensure_ready()` concurrently with differing configurations, each thread immediately supersedes and terminates the other's in-flight startup, resulting in an unbounded ping-pong livelock.
5. **RS-06 (Windows Job Object Containment — CONFIRMED, DESIGN DETAIL)**: Verified in `process.rs:27–56`. Child processes are launched via `std::process::Command` with `CREATE_NO_WINDOW` but without Windows Job Object assignment (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`). An abnormal crash of NVDA or the supervisor process leaks the runtime server tree and VRAM.
6. **RS-10 (Clean Test Shims Scope Resolution — CONFIRMED, BLOCKER)**: The production PyO3 interface in `runtime_supervisor/src/lib.rs` is already clean: zero mock shims exist in production Rust code (all mocks are isolated under `#[cfg(test)] mod tests;`). However, duplicate Python test shims (`_TestShimSupervisor` and `_LlamaTestShimSupervisor`) exist in `server.py:322–415` and `llama_server.py:91–178`. In the migration roadmap, these Python shims are actively required by existing Python tests and are scheduled for deletion in **Slice 8** once runtime ownership is relocated to the Worker process.
7. **Test Suite Coverage**: 11 existing unit tests in `runtime_supervisor/src/tests.rs` pass cleanly. A comprehensive suite of 9 new regression tests has been specified to guarantee verification of all Slice 0 fixes.

---

## 2. Deep Dive: RS-01 (Generation Counter Omission)

### 2.1 Code Observation & Exact Locations
In `runtime_supervisor/src/supervisor.rs`, `InnerState::generation` (a `u64`) serves as the monotonic epoch counter for generation fencing across asynchronous callers and external observers (Invariant A9).

The audit identified three distinct code paths where `state.state` transitions to `LifecycleState::Failed` or `LifecycleState::Stopped` without incrementing `state.generation`:

#### Location 1: `refresh_process_state_locked` (`supervisor.rs:126–150`)
```rust
126: fn refresh_process_state_locked(&self, state: &mut InnerState) {
127:     if state.state == LifecycleState::ReadyOwned || state.state == LifecycleState::Starting {
128:         if let Some(ref mut process) = state.process {
129:             match process.poll() {
130:                 Ok(Some(exit_code)) => {
131:                     state.process = None;
132:                     if exit_code != 0 {
133:                         state.state = LifecycleState::Failed;
134:                         state.last_error = Some(format!(
135:                             "{} server process exited unexpectedly with code {}",
136:                             self.runtime_name, exit_code
137:                         ));
138:                     } else {
139:                         state.state = LifecycleState::Stopped;
140:                     }
141:                     self.condvar.notify_all();
                         // DEFECT: state.generation is NOT incremented!
142:                 }
143:                 Ok(None) => {}
144:                 Err(e) => {
145:                     state.last_error = Some(e);
146:                 }
147:             }
148:         }
149:     }
150: }
```
- **Callers**: Called non-blockingly by `status()` (`line 103`), `matches_startup_configuration()` (`line 120`), `ensure_ready()` (`line 170`), and `adopt()` (`line 509`).
- **Defect**: When a running server crashes (e.g. exit code 137 or segfault), `status()` transitions the state to `Failed` and removes the process handle, but leaves `state.generation` completely unchanged.

#### Location 2: Startup In-Flight Crash Detection (`supervisor.rs:358–370`)
```rust
358: if let Some(ref mut proc) = s.process {
359:     if let Ok(Some(code)) = proc.poll() {
360:         s.process = None;
361:         s.state = LifecycleState::Failed;
362:         let err_msg = format!(
363:             "{} server process exited unexpectedly with code {}",
364:             self.runtime_name, code
365:         );
366:         s.last_error = Some(err_msg.clone());
367:         self.condvar.notify_all();
             // DEFECT: s.generation is NOT incremented!
368:         return Err(err_msg);
369:     }
370: }
```
- **Defect**: If the child exits during the health-polling loop in `ensure_ready`, state transitions `Starting -> Failed`, but generation remains `my_gen`.

#### Location 3: Readiness Timeout Expiry (`supervisor.rs:408–428`)
```rust
406: let mut s = self.state.lock().unwrap();
407: if s.generation == my_gen {
408:     if let Some(mut proc) = s.process.take() {
409:         if let Ok(Some(code)) = proc.poll() {
410:             s.state = LifecycleState::Failed;
                 // DEFECT: s.generation is NOT incremented!
...
418:         }
419:         let _ = proc.terminate();
420:     }
421:     s.state = LifecycleState::Failed;
422:     let err_msg = format!(
423:         "{} server did not become ready within timeout",
424:         self.runtime_name
425:     );
426:     s.last_error = Some(err_msg.clone());
427:     self.condvar.notify_all();
         // DEFECT: s.generation is NOT incremented!
428:     return Err(err_msg);
429: }
```
- **Defect**: When startup times out, `proc` is terminated and state becomes `Failed`, but `s.generation` is not incremented.

#### Location 4: Spawn Failure (`supervisor.rs:327–333`)
```rust
327: match spawn_result {
328:     Err(err) => {
329:         state.state = LifecycleState::Failed;
330:         state.last_error = Some(err.clone());
331:         self.condvar.notify_all();
             // DEFECT: state.generation remains at the starting generation
332:         return Err(err);
333:     }
```

### 2.2 Architectural Impact
1. **Broken Generation Fencing**: In Slice 3 and Worker IPC designs, external clients and the watchdog poll `status()`. If a crash occurs and generation does not advance, downstream consumers cannot differentiate a newly failed generation from stale status updates belonging to the previous running session.
2. **Condvar Spurious Wakeups**: Waiting threads checking `s.generation == my_gen` may misinterpret a crashed state as still belonging to the current epoch instead of a concluded epoch.

### 2.3 Proposed Remediation
Increment `generation += 1` on every terminal exit and failure transition:
```rust
// In refresh_process_state_locked:
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
```
Apply corresponding `generation += 1` increments in lines 360, 410, 421, and 329.

---

## 3. Deep Dive: RS-02 (Missing Stopping Guard)

### 3.1 Code Observation & Exact Locations
In `runtime_supervisor/src/supervisor.rs`, examine `stop()` (`lines 470–498`) and `ensure_ready()` (`lines 168–275`):

```rust
470: pub fn stop(&self, timeout: Duration) -> Result<RuntimeStatus, String> {
471:     let mut state = self.state.lock().unwrap();
472:     state.generation += 1;
473:     state.state = LifecycleState::Stopping;
474:     let mut proc_opt = state.process.take();
475:     state.startup_identity = None;
476:     state.running_model = None;
477:     self.condvar.notify_all();
478:     drop(state); // <--- Lock dropped!
479: 
480:     if let Some(ref mut proc) = proc_opt {
481:         let _ = proc.terminate();
482:         let _ = proc.wait_timeout(timeout); // <--- Can block for 5-10 seconds!
483:     }
484: 
485:     let mut state = self.state.lock().unwrap();
486:     state.state = LifecycleState::Stopped; // <--- UNCONDITIONAL OVERWRITE!
487:     self.condvar.notify_all();
488:     ...
```

Now trace `ensure_ready()` while Thread A is inside `wait_timeout` at line 482:
```rust
168: 'outer: loop {
169:     let mut state = self.state.lock().unwrap();
170:     self.refresh_process_state_locked(&mut state);
171: 
172:     // 1. ReadyOwned matching current configuration
173:     if state.state == LifecycleState::ReadyOwned { ... }
198:     // 2. ReadyAdopted
199:     if state.state == LifecycleState::ReadyAdopted { ... }
224:     // 3. In-flight Starting
225:     if state.state == LifecycleState::Starting { ... }
270: 
271:     // 4. Stopped or Failed: begin transition to Starting under lock
272:     state.generation += 1;
273:     let my_gen = state.generation;
274:     state.state = LifecycleState::Starting;
```
Notice: `ensure_ready()` checks only `ReadyOwned`, `ReadyAdopted`, and `Starting`. When `state.state == LifecycleState::Stopping`, it falls through straight into Step 4!
It increments generation to 3, sets `state = Starting`, releases the lock, and calls `self.process_driver.spawn(...)`!

### 3.2 Race Condition & Zombie Process Mechanism
1. Thread A calls `stop()`: `generation = 2`, `state = Stopping`. Lock is released. Thread A waits for the old child to terminate (up to 5s).
2. Thread B calls `ensure_ready()`: sees `state == Stopping`, bypasses all checks, falls into step 4, transitions to `Starting` (`generation = 3`), drops the lock, and successfully spawns Child B.
3. Thread B reacquires the lock, attaches `state.process = Some(Child B)`, and begins polling health.
4. Thread A finishes waiting for Child A. Thread A acquires the lock at line 485.
5. Thread A **unconditionally overwrites** `state.state = LifecycleState::Stopped`!
6. If Child B becomes healthy, Thread B checks lines 396–398:
   `if s.state == LifecycleState::Stopped || s.state == LifecycleState::Stopping { return Err("server startup was stopped"); }`
   Thread B aborts with an error, but Child B is already running!
7. `state.process` may retain Child B, or a subsequent `ensure_ready` call will wipe it out and spawn Child C.
8. Child B is now an **untracked zombie process** running in the background, consuming several gigabytes of GPU VRAM and holding port 9379/8080!

### 3.3 Proposed Remediation
Two mutually reinforcing guards are required:

1. **In `ensure_ready()` (`lines 170–172`)**: Add an explicit `Stopping` guard that waits on `condvar`:
```rust
if state.state == LifecycleState::Stopping {
    let remaining = timeout.saturating_sub(start_time.elapsed());
    if remaining.is_zero() {
        return Err(format!("{} server stop timed out before startup could begin", self.runtime_name));
    }
    let (new_state, wait_res) = self
        .condvar
        .wait_timeout_while(state, remaining, |s| s.state == LifecycleState::Stopping)
        .unwrap();
    state = new_state;
    if wait_res.timed_out() && state.state == LifecycleState::Stopping {
        return Err(format!("Timed out waiting for {} server to stop", self.runtime_name));
    }
    continue 'outer;
}
```

2. **In `stop()` (`lines 472, 485–487`)**: Capture generation and guard the terminal write:
```rust
let my_gen = state.generation; // captured at line 472
...
let mut state = self.state.lock().unwrap();
if state.generation == my_gen {
    state.state = LifecycleState::Stopped;
    self.condvar.notify_all();
}
```

---

## 4. Deep Dive: RS-03 (Socket Collision on Restart)

### 4.1 Code Observation & Exact Locations
In `runtime_supervisor/src/supervisor.rs:448–467`:
```rust
448: pub fn restart(...) -> Result<RuntimeStatus, String> {
449:     let mut state = self.state.lock().unwrap();
450:     state.generation += 1;
451:     state.state = LifecycleState::Restarting;
452:     if let Some(mut proc) = state.process.take() {
453:         let _ = proc.terminate(); // <--- Terminate sent, but NO WAIT!
454:     }
455:     state.startup_identity = None;
456:     state.running_model = None;
457:     self.condvar.notify_all();
458:     drop(state);
459: 
460:     self.ensure_ready( // <--- Called immediately!
461:         executable,
462:         args,
463:         env,
464:         startup_identity,
465:         running_model,
466:         timeout,
467:     )
468: }
```

### 4.2 Mechanism of Failure
1. In `process.rs:76–80`, `terminate()` calls `self.child.kill()`, which on Windows invokes `TerminateProcess(hProcess, 1)`.
2. Win32 `TerminateProcess` is **asynchronous**: it signals termination to the OS kernel and returns immediately.
3. When `restart()` drops the lock and calls `ensure_ready()` (line 460), the old process has not finished tearing down its TCP listening socket (e.g., port 9379 for LiteRT, 8080 for llama-server).
4. `ensure_ready()` checks lines 286–289:
   `if self.health_checker.check_compatible(&self.base_url, Duration::from_millis(500))`
   - **Hazard A (Zombie Adoption)**: If the dying server's socket is still answering HTTP GET `/v1/models` during teardown, `ensure_ready()` falsely assumes an external server exists and transitions to `ReadyAdopted`. Moments later, the old server exits, leaving the supervisor in `ReadyAdopted` with a dead endpoint.
   - **Hazard B (Socket Collision / `WSAEADDRINUSE`)**: If `check_compatible` fails, `ensure_ready()` immediately spawns the new server process. When the new process attempts `bind()` on port 9379/8080, Windows rejects the bind with WinSock error `10048` (`WSAEADDRINUSE`: "Only one usage of each socket address is normally permitted"). The new server process crashes with exit code 1.

### 4.3 Proposed Remediation
1. In `restart()`, keep the `old_proc` handle:
```rust
let mut old_proc = state.process.take();
...
drop(state);

if let Some(ref mut proc) = old_proc {
    let _ = proc.terminate();
    let drain_timeout = Duration::from_secs(5).min(timeout);
    let _ = proc.wait_timeout(drain_timeout);
}

// Await port release before launching new server
let port_deadline = Instant::now() + Duration::from_millis(1500).min(timeout);
while Instant::now() < port_deadline {
    if !self.health_checker.check_health(&self.base_url, Duration::from_millis(50)) {
        break;
    }
    std::thread::sleep(Duration::from_millis(50));
}

self.ensure_ready(...)
```

---

## 5. Deep Dive: RS-04 (`ensure_ready` Livelock)

### 5.1 Code Observation & Exact Locations
In `runtime_supervisor/src/supervisor.rs:223–269` and `314–325`:
```rust
224: if state.state == LifecycleState::Starting {
225:     if let Some(ref active) = state.active_config {
226:         if active.startup_identity == startup_identity {
227:             // Matching config waits on condvar...
228:             let my_gen = state.generation;
229:             ...
241:         }
242:     }
264:     // Config differs while starting: supersede current startup
265:     state.generation += 1;
266:     if let Some(mut old_proc) = state.process.take() {
267:         let _ = old_proc.terminate();
268:     }
269: }
```
And during post-spawn check (`lines 314–325`):
```rust
314: let mut state = self.state.lock().unwrap();
315: if state.generation != my_gen {
316:     if let Ok(mut child) = spawn_result {
317:         let _ = child.terminate();
318:     }
319:     if state.state == LifecycleState::Stopped || state.state == LifecycleState::Stopping {
320:         return Err(format!("{} server startup was stopped", self.runtime_name));
321:     }
322:     continue 'outer;
323: }
```

### 5.2 Ping-Pong Livelock Mechanism
When two callers concurrently invoke `ensure_ready` with different configurations (e.g. Model A vs Model B during rapid UI toggling or parallel provider readiness checks):
1. Thread 1 initiates Config A: `generation = 1`, `state = Starting`. Drops lock, begins `spawn(Config A)`.
2. Thread 2 enters `ensure_ready` with Config B. Sees `state == Starting`. Since `startup_identity` differs, Thread 2 hits line 265: increments `generation = 2`, terminates any existing process, enters Step 4, increments `generation = 3`, sets `active_config = Config B`, and begins `spawn(Config B)`.
3. Thread 1 finishes spawning Child A, acquires the lock at line 314, observes `state.generation (3) != my_gen (1)`, terminates Child A, and loops back to `'outer`.
4. Thread 1 enters `'outer`, sees `state == Starting` with Config B, observes `Config B != Config A`, hits line 265, increments `generation = 4`, kills Thread 2's process, increments `generation = 5`, sets `active_config = Config A`, and spawns Child A again.
5. Thread 2 finishes spawning Child B, observes generation mismatch (5 != 3), kills Child B, loops to `'outer`, and supersedes Thread 1 again.
6. **Result**: Both threads enter an unbounded ping-pong livelock, endlessly spawning and killing each other's processes, exhausting OS handles, saturating CPU, and failing Invariant A9.

### 5.3 Proposed Remediation
Instead of immediately superseding an in-flight startup, a conflicting caller must wait on `condvar` for the in-flight startup to complete or fail:
```rust
if state.state == LifecycleState::Starting {
    let my_gen = state.generation;
    let remaining = timeout.saturating_sub(start_time.elapsed());
    if remaining.is_zero() {
        return Err(format!("{} server readiness timed out", self.runtime_name));
    }
    let (new_state, _) = self
        .condvar
        .wait_timeout_while(state, remaining, |s| {
            s.state == LifecycleState::Starting && s.generation == my_gen
        })
        .unwrap();
    state = new_state;
    // After waking: if the completed state matches, return it.
    // If it does not match (different config), the next iteration will see ReadyOwned
    // and invoke restart(), or see Failed/Stopped and start cleanly.
    continue 'outer;
}
```
Furthermore, add a bounded retry counter (`const MAX_ATTEMPTS: usize = 5`) with exponential backoff on retries to circuit-break transient startup failures.

---

## 6. Deep Dive: RS-06 (Windows Job Object Containment)

### 6.1 Code Observation & Current Spawning Mechanics
In `runtime_supervisor/src/process.rs:27–56`:
```rust
27: pub struct OsProcessDriver;
28: 
29: impl ProcessDriver for OsProcessDriver {
30:     fn spawn(
31:         &self,
32:         executable: &str,
33:         args: &[String],
34:         env: &HashMap<String, String>,
35:     ) -> Result<Box<dyn ProcessHandle>, String> {
36:         let mut cmd = Command::new(executable);
37:         cmd.args(args);
38:         for (k, v) in env {
39:             cmd.env(k, v);
40:         }
41:         #[cfg(windows)]
42:         cmd.creation_flags(CREATE_NO_WINDOW);
43: 
44:         cmd.stdout(Stdio::null());
45:         cmd.stderr(Stdio::null());
46: 
47:         let child = cmd
48:             .spawn()
49:             .map_err(|e| format!("Failed to spawn process '{}': {}", executable, e))?;
50: 
51:         Ok(Box::new(OsProcessHandle {
52:             pid: child.id(),
53:             child,
54:         }))
55:     }
56: }
```
- Spawning uses standard `std::process::Command` with `CREATE_NO_WINDOW` (`0x08000000`).
- No Job Object is created or associated.
- On Windows, if `nvda.exe` crashes (unhandled exception, C++ assertion failure, `taskkill /F`), all child processes spawned without a Job Object continue running as orphaned background processes, holding TCP listening sockets and GPU VRAM.

### 6.2 Available Crates & Dependency Analysis
In `runtime_supervisor/Cargo.toml`, current dependencies are:
```toml
[dependencies]
pyo3 = { version = "0.23", features = ["extension-module"] }
ureq = { version = "2", features = ["json"] }
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
```
Neither `windows-sys` nor `winapi` is currently present in `runtime_supervisor/Cargo.toml`.
However, in `nvda_ui_host/Cargo.toml`, the crate `windows = "0.62"` is already used and downloaded in the cargo cache.

### 6.3 Implementation Options & Recommendation

#### Option A: Target-Specific `windows` Crate Dependency
In `runtime_supervisor/Cargo.toml`:
```toml
[target.'cfg(windows)'.dependencies]
windows = { version = "0.62", features = [
    "Win32_Foundation",
    "Win32_System_JobObjects",
    "Win32_System_Threading",
] }
```
- **Pros**: Strong typing, idiomatic Windows API bindings matching `nvda_ui_host`.
- **Cons**: Adds compilation time for Windows metadata parsing.

#### Option B: Zero-Dependency Raw Win32 FFI (Recommended for Efficiency)
Win32 Job Objects require exactly 4 C functions exported by `kernel32.dll` on all Windows versions:
`CreateJobObjectW`, `SetInformationJobObject`, `AssignProcessToJobObject`, and `CloseHandle`.
Defining them directly in `process.rs` under `#[cfg(windows)]`:
```rust
#[cfg(windows)]
mod job_object {
    use std::os::windows::io::AsRawHandle;
    use std::ptr::null_mut;

    type HANDLE = *mut std::ffi::c_void;
    type BOOL = i32;

    const JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: u32 = 0x2000;
    const JobObjectExtendedLimitInformation: i32 = 9;

    #[repr(C)]
    struct IO_COUNTERS {
        read_operation_count: u64,
        write_operation_count: u64,
        other_operation_count: u64,
        read_transfer_count: u64,
        write_transfer_count: u64,
        other_transfer_count: u64,
    }

    #[repr(C)]
    struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
        per_process_user_time_limit: i64,
        per_job_user_time_limit: i64,
        limit_flags: u32,
        minimum_working_set_size: usize,
        maximum_working_set_size: usize,
        active_process_limit: u32,
        affinity: usize,
        priority_class: u32,
        scheduling_class: u32,
    }

    #[repr(C)]
    struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
        basic_limit_information: JOBOBJECT_BASIC_LIMIT_INFORMATION,
        io_info: IO_COUNTERS,
        process_memory_limit: usize,
        job_memory_limit: usize,
        peak_process_memory_limit: usize,
        peak_job_memory_limit: usize,
    }

    extern "system" {
        fn CreateJobObjectW(lp_job_attributes: *mut std::ffi::c_void, lp_name: *const u16) -> HANDLE;
        fn SetInformationJobObject(
            h_job: HANDLE,
            job_object_info_class: i32,
            lp_job_object_info: *const std::ffi::c_void,
            cb_job_object_info_length: u32,
        ) -> BOOL;
        fn AssignProcessToJobObject(h_job: HANDLE, h_process: HANDLE) -> BOOL;
        fn CloseHandle(h_object: HANDLE) -> BOOL;
    }

    pub struct JobHandle(HANDLE);
    unsafe impl Send for JobHandle {}
    unsafe impl Sync for JobHandle {}

    impl JobHandle {
        pub fn create_kill_on_close() -> Result<Self, String> {
            unsafe {
                let h_job = CreateJobObjectW(null_mut(), null_mut());
                if h_job.is_null() {
                    return Err("Failed to create Win32 Job Object".into());
                }
                let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
                info.basic_limit_information.limit_flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
                let res = SetInformationJobObject(
                    h_job,
                    JobObjectExtendedLimitInformation,
                    &info as *const _ as *const _,
                    std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                );
                if res == 0 {
                    CloseHandle(h_job);
                    return Err("Failed to set Job Object extended limit information".into());
                }
                Ok(JobHandle(h_job))
            }
        }

        pub fn assign_process(&self, process_handle: std::os::windows::io::RawHandle) -> Result<(), String> {
            unsafe {
                let res = AssignProcessToJobObject(self.0, process_handle as HANDLE);
                if res == 0 {
                    return Err("Failed to assign process to Job Object".into());
                }
                Ok(())
            }
        }
    }

    impl Drop for JobHandle {
        fn drop(&mut self) {
            if !self.0.is_null() {
                unsafe { CloseHandle(self.0); }
            }
        }
    }
}
```
- **Lifecycle & Containment**: `OsProcessHandle` retains ownership of `JobHandle`. If `nvda.exe` or the supervisor crashes, the OS kernel automatically closes all handles in the process handle table, which closes the `JobHandle`, immediately triggering `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` to terminate the entire child process hierarchy.

---

## 7. Deep Dive: RS-10 (Clean Test Shims Scope Analysis)

### 7.1 Rust PyO3 Boundary Inspection (`runtime_supervisor/src/lib.rs`)
Inspection of `runtime_supervisor/src/lib.rs` (154 lines) reveals:
- The exported PyO3 module `runtime_supervisor` adds exactly two classes:
  1. `RuntimeStatus` (`pyclass(frozen)`)
  2. `RuntimeSupervisor` (`pyclass`)
- **Zero test mock or shadow shims** exist in `lib.rs`, `types.rs`, `supervisor.rs`, `process.rs`, or `health.rs`.
- All fake implementations (`FakeProcessHandle`, `FakeProcessDriver`, `FakeHealthChecker`) are isolated strictly under `#[cfg(test)] mod tests;` in `tests.rs`.
- `cargo test --manifest-path runtime_supervisor/Cargo.toml` compiles them solely in test builds; release artifacts (`.pyd`) contain zero test mock artifacts.
- **Conclusion for Rust PyO3 interface**: Fully compliant with Invariant A7.

### 7.2 Python Production Code Inspection (`server.py` and `llama_server.py`)
In the Python add-on codebase, two duplicate test shims exist:
1. `_TestShimSupervisor` in `addon/globalPlugins/AI-assistant/providers/runtime/server.py:322–415`
2. `_LlamaTestShimSupervisor` in `addon/globalPlugins/AI-assistant/providers/runtime/llama_server.py:91–178`

#### Why do they exist?
When `test_local_provider_lifecycle.py`, `test_server.py`, or `test_llama_server.py` run in pure-Python test environments without native binaries or on machines where `_run_litert_cli` or `process_factory` is monkeypatched, `server.py` (`lines 529–531`) and `llama_server.py` (`lines 284–287`) dynamically instantiate these shadow Python supervisors instead of calling native `RuntimeSupervisor`.

#### Roadmap & Clarification of RS-10 Scope
- The master architecture deliverable assigns the deletion of `_TestShimSupervisor` and `_LlamaTestShimSupervisor` to **Slice 8** (`architecture_deliverable.md:1064–1065`, `1234`):
  > *Slice 8: Removal of Obsolete NVDA-Side Runtime Threading*
  > *- providers/runtime/server.py (Delete `_TestShimSupervisor`, RS-10)*
  > *- providers/runtime/llama_server.py (Delete `_LlamaTestShimSupervisor`, RS-10)*
- **Hazard of premature deletion in Slice 0**: Deleting these Python classes in Slice 0 immediately breaks 14+ tests in `tests/integration/test_local_provider_lifecycle.py` and `tests/providers/runtime/test_server.py` that rely on them for process mocking.
- **Slice 0 Action for RS-10**:
  1. Formally verify and lock the Rust PyO3 interface to ensure zero test mock shims in native binary exports.
  2. Document the clean contract boundary and dependency linkage to prepare for Slice 8 deconstruction.

---

## 8. Existing Tests & Regression Test Specifications

### 8.1 Existing Tests in `runtime_supervisor/src/tests.rs`
The existing test suite comprises 11 tests:

| Test Name | Lines | Purpose / Coverage |
| :--- | :---: | :--- |
| `test_simultaneous_ensure_ready_calls_deduplicate` | 134–167 | 5 concurrent threads calling `ensure_ready` spawn only 1 child process. |
| `test_child_exits_immediately_after_spawn` | 170–195 | Spawns child with exit code 42; verifies failure status and error string. |
| `test_child_exits_after_becoming_ready` | 197–222 | Process crash (code 137) detected by non-blocking `status()` query. |
| `test_config_change_restarts_running_server` | 225–269 | Calling `ensure_ready` with changed configuration restarts and spawns 2nd process. |
| `test_adopted_server_detected_and_reused` | 272–295 | Compatible and healthy endpoint adopted without spawning. |
| `test_adopted_server_disappears_triggers_spawn` | 297–334 | If adopted endpoint stops responding, next `ensure_ready` spawns owned process. |
| `test_stop_during_startup_cancels_cleanly` | 336–365 | Calling `stop()` while `ensure_ready` is in `starting` aborts startup cleanly. |
| `test_stale_generation_does_not_overwrite_newer_state` | 368–403 | Verifies generation advances on restart (to generation 3) with new startup identity. |
| `test_wrong_unrelated_server_on_endpoint_is_not_adopted` | 406–425 | Incompatible server on port is rejected; owned process spawned instead. |
| `test_os_process_driver_exit_code` | 427–436 | Real OS command `cmd.exe /C exit 42` returns code 42. |
| `test_ensure_ready_with_os_process_child_exit` | 439–452 | Real OS command exit code captured as error in `ensure_ready`. |

### 8.2 Mandatory Regression Tests for Slice 0 Implementation

To verify RS-01, RS-02, RS-03, RS-04, and RS-06, the following 9 tests must be implemented in `runtime_supervisor/src/tests.rs`:

#### 1. RS-01 Regression Tests (Generation Monotonicity)
- **`test_child_crash_increments_generation_in_status`**:
  Start server to `ReadyOwned` at generation $G_0$. Simulate crash (`alive.store(false)`). Call `status()`.
  Assert `status.state == "failed"`.
  Assert `status.generation == G_0 + 1` (must advance epoch on crash detection).
- **`test_startup_child_crash_increments_generation`**:
  Child process exits during `ensure_ready` polling loop.
  Assert `ensure_ready` returns error.
  Assert `supervisor.status().generation > G_start`.
- **`test_readiness_timeout_increments_generation`**:
  Child process remains alive but health check never passes. `ensure_ready` times out.
  Assert `supervisor.status().state == "failed"`.
  Assert `supervisor.status().generation > G_start`.

#### 2. RS-02 Regression Tests (Stopping Guard)
- **`test_ensure_ready_blocks_and_waits_if_stopping`**:
  Simulate slow-stopping process handle (e.g. `wait_timeout` sleeps 100ms before returning).
  Thread 1 calls `stop()`.
  Thread 2 concurrently calls `ensure_ready()`.
  Assert Thread 2 does not spawn a new process while state is `Stopping`.
  Assert Thread 2 waits for `Stopped`, then cleanly starts.
  Assert total process spawns equals 1 (no orphaned zombie process).
- **`test_stop_does_not_overwrite_newer_generation`**:
  Simulate race where `stop()` completes after another generation has taken over.
  Assert `stop()` does not overwrite `state.state` back to `Stopped` if generation changed.

#### 3. RS-03 Regression Tests (Socket Teardown & Wait on Restart)
- **`test_restart_waits_for_old_process_exit`**:
  Configure fake process handle with tracked termination completion.
  Call `restart()`.
  Assert `wait_timeout` was invoked on old process before new process was spawned.
- **`test_restart_does_not_adopt_dying_server`**:
  Endpoint health responds during the first 50ms of termination.
  Call `restart()`.
  Assert supervisor does not adopt the dying server as `ReadyAdopted`.

#### 4. RS-04 Regression Tests (Concurrent Conflicting Configs)
- **`test_concurrent_conflicting_configs_no_livelock`**:
  Spawn two concurrent threads calling `ensure_ready` with "config-A" and "config-B".
  Assert both threads complete within 3 seconds.
  Assert total process spawns is bounded ($\le 2$), proving absence of infinite ping-pong livelock.

#### 5. RS-06 Regression Tests (Job Object Containment)
- **`test_os_process_handle_job_object_containment`** (`#[cfg(windows)]`):
  Spawn a dummy test process using `OsProcessDriver`.
  Query Win32 `IsProcessInJob`.
  Assert the spawned child process is actively assigned to a valid Windows Job Object.

---

## 9. Synthesis & Recommended Action Plan for Slice 0 Implementation

| Step | Action Item | Target File | Scope / Impact |
| :---: | :--- | :--- | :--- |
| **1** | Implement RS-01 generation increments | `runtime_supervisor/src/supervisor.rs` | Increment `generation += 1` on child exit in `refresh_process_state_locked`, startup crash poll, and timeout. |
| **2** | Implement RS-02 stopping guard | `runtime_supervisor/src/supervisor.rs` | Add condvar wait in `ensure_ready` while `Stopping`; guard `stop()` state write with `if state.generation == my_gen`. |
| **3** | Implement RS-03 restart process wait | `runtime_supervisor/src/supervisor.rs` | Await `wait_timeout` and port quiescence in `restart()` before launching new server. |
| **4** | Implement RS-04 condvar waiting on conflict | `runtime_supervisor/src/supervisor.rs` | Wait on condvar when encountering in-flight `Starting` with different config; add bounded retry counter. |
| **5** | Implement RS-06 Windows Job Object | `runtime_supervisor/src/process.rs` | Add Win32 Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` to `OsProcessDriver`. |
| **6** | Verify RS-10 production interface cleanliness | `runtime_supervisor/src/lib.rs` | Confirm zero mock shims in PyO3 exports; defer Python shim deletion to Slice 8. |
| **7** | Add full regression test suite | `runtime_supervisor/src/tests.rs` | Implement 9 new regression tests covering RS-01 to RS-06. |
| **8** | Run complete validation gate | All targets | Verify `cargo test --manifest-path runtime_supervisor/Cargo.toml`, `cargo check --manifest-path nvda_ui_host/Cargo.toml`, `uv run ruff check .`, `uv run pytest`. |

---
*End of Survey Report.*
