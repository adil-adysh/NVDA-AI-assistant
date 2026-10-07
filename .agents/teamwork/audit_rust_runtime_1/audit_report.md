# Audit E: Rust Runtime Supervisor Verification & Concurrency Audit

- **Auditor**: Rust Runtime & Concurrency Auditor (Agent 3)
- **Repository Root**: `D:\nvda-addons\NVDA-AI-assistant`
- **Working Directory**: `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\audit_rust_runtime_1`
- **Commit HEAD**: `ced1cbc`
- **Date**: 2026-10-02
- **Status**: Complete & Verified

---

## 1. Executive Summary & Audit Scope

This audit provides an exhaustive, code-level verification of the native Rust `runtime_supervisor` crate (`runtime_supervisor/`), its PyO3 bindings, and its integration with the Python application layer (`addon/globalPlugins/AI-assistant/providers/runtime/` and `plugin/background.py`) at commit HEAD (`ced1cbc`).

The primary purpose of `runtime_supervisor` is to act as the authoritative native owner of managed local AI runtimes (`LiteRT-LM` and `llama-server`), providing deterministic process lifecycle management, in-flight startup deduplication, monotonic generation fencing, health monitoring, and graceful teardown.

### Core Audit Scope
1. **Lifecycle State Machine**: Comprehensive transition validation across `Stopped` (Unloaded), `Starting`, `ReadyOwned`, `ReadyAdopted`, `Restarting`, `Stopping`, and `Failed`.
2. **Concurrency & Synchronization**: Analysis of mutex lock contention, `Condvar` wait/notify semantics, concurrent `ensure_ready` deduplication, generation fencing, shutdown races, and deadlock/livelock risks.
3. **Process Mechanics**: OS process spawning, death detection, graceful vs. forceful kill semantics, Windows Job Objects, process tree management, port contention (`WSAEADDRINUSE`), and diagnostic capture (`stderr`).
4. **Startup Identity & Adoption**: Verification of endpoint health/compatibility checks, model identity validation, adoption across restarts, and adopted server reconfiguration traps.
5. **PyO3 Boundary & Python Interaction**: Python GIL release verification (`py.allow_threads`), error mapping, and architectural contamination (production test shims).
6. **Invariant Conformance**: Compliance against Invariants A7–A10 and A25–A26.

### Summary Assessment
While the introduction of `runtime_supervisor` in commit `2e0d7a9` represents a major architectural improvement—successfully moving core serialization from error-prone Python locks to Rust mutex/condvar synchronization and correctly releasing the GIL during blocking calls—**four critical BLOCKER concurrency flaws and several severe design gaps were identified** that must be resolved before expanding its ownership to the target Worker process topology.

---

## 2. Lifecycle State Machine Audit

### 2.1 State Definitions
The lifecycle state machine is implemented in `runtime_supervisor/src/types.rs` (lines 7–41) and `runtime_supervisor/src/supervisor.rs` (lines 17–25):

```rust
// runtime_supervisor/src/types.rs:7-15
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LifecycleState {
    Stopped,
    Starting,
    ReadyOwned,
    ReadyAdopted,
    Restarting,
    Stopping,
    Failed,
}
```

- **`Stopped`**: No process is running; no external server is adopted. Equivalent to target "Unloaded".
- **`Starting`**: Process spawn or compatibility check is underway; health polling in progress.
- **`ReadyOwned`**: Child process was spawned by the supervisor, passed health check, and its `ProcessHandle` is owned.
- **`ReadyAdopted`**: An existing process on the endpoint was verified compatible and healthy; no `ProcessHandle` is owned.
- **`Restarting`**: Existing process was signaled to terminate; transitioning immediately into a new startup sequence.
- **`Stopping`**: Process is actively being terminated and awaited.
- **`Failed`**: Process crashed, failed to spawn, or health readiness timed out.

### 2.2 Complete State Transition Matrix

| Current State | Trigger / Method | Target State | Generation Incremented? | Code Location | Conformance / Risk |
|---|---|---|---|---|---|
| `Stopped` | `ensure_ready` (compatible) | `ReadyAdopted` | Yes (`+1`) | `supervisor.rs:272, 292` | Valid |
| `Stopped` | `ensure_ready` (spawn ok) | `ReadyOwned` | Yes (`+1`) | `supervisor.rs:272, 380` | Valid |
| `Stopped` | `ensure_ready` (spawn fail) | `Failed` | Yes (`+1`) | `supervisor.rs:272, 329` | Valid |
| `Stopped` | `adopt` (compatible) | `ReadyAdopted` | Yes (`+1`) | `supervisor.rs:529, 530` | Valid |
| `Starting` | health check success | `ReadyOwned` | No (retains gen) | `supervisor.rs:380` | Valid |
| `Starting` | child exit detected | `Failed` | **NO (STALE GEN)** | `supervisor.rs:361` | **CRITICAL BUG (RS-01)** |
| `Starting` | timeout expired | `Failed` | **NO (STALE GEN)** | `supervisor.rs:421` | **CRITICAL BUG (RS-01)** |
| `Starting` | new matching config | `Starting` (waits) | No (deduplicates) | `supervisor.rs:236` | Valid |
| `Starting` | new differing config | `Starting` (supersedes) | Yes (`+1`) | `supervisor.rs:265` | **LIVELOCK RISK (RS-04)** |
| `Starting` | `stop()` called | `Stopping` | Yes (`+1`) | `supervisor.rs:472` | Valid |
| `ReadyOwned` | child exits (code != 0) | `Failed` | **NO (STALE GEN)** | `supervisor.rs:133` | **CRITICAL BUG (RS-01)** |
| `ReadyOwned` | child exits (code == 0) | `Stopped` | **NO (STALE GEN)** | `supervisor.rs:139` | **CRITICAL BUG (RS-01)** |
| `ReadyOwned` | config changed | `Restarting` | Yes (`+1`) | `supervisor.rs:188, 450` | Valid |
| `ReadyOwned` | `stop()` called | `Stopping` | Yes (`+1`) | `supervisor.rs:472` | Valid |
| `ReadyAdopted`| health check fails | `Stopped` | **NO (STALE GEN)** | `supervisor.rs:219` | **STALE GEN (RS-01)** |
| `ReadyAdopted`| config changed | `ReadyAdopted` | No | `supervisor.rs:199` | **TRAP (RS-05)** |
| `Stopping` | wait completes | `Stopped` | No | `supervisor.rs:486` | **RACE HAZARD (RS-02)** |
| `Stopping` | `ensure_ready` called | `Starting` | Yes (`+1`) | `supervisor.rs:272` | **RACE HAZARD (RS-02)** |
| `Restarting` | `ensure_ready` called | `Starting` | Yes (`+1`) | `supervisor.rs:272` | **RACE HAZARD (RS-03)** |
| `Failed` | `ensure_ready` | `Starting` | Yes (`+1`) | `supervisor.rs:272` | Valid |
| `Failed` | `stop()` | `Stopped` | Yes (`+1`) | `supervisor.rs:472` | Valid |

---

## 3. Concurrency & Synchronization Audit

### 3.1 In-Flight Startup Deduplication
The deduplication mechanism in `SupervisorCore::ensure_ready` (`supervisor.rs:223–263`) handles multiple concurrent callers requesting the same startup configuration:
```rust
// supervisor.rs:224-242
if state.state == LifecycleState::Starting {
    if let Some(ref active) = state.active_config {
        if active.startup_identity == startup_identity {
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
```
- **Evaluation**: This design correctly drops the mutex during the wait and re-evaluates the predicate on wakeup. Verified by test `tests::test_simultaneous_ensure_ready_calls_deduplicate` (5 concurrent threads, exactly 1 process spawn).
- **Minor Flaw**: If `wait_timeout_while` times out, line 261 executes `continue 'outer;` instead of immediately returning an error, causing one extra loop iteration before returning the timeout error at line 230.

### 3.2 Finding RS-01 (CONFIRMED / BLOCKER): Generation Counter Fails to Increment on Process Crashes & Timeouts
- **Location**: `runtime_supervisor/src/supervisor.rs:130–141`, `supervisor.rs:358–370`, `supervisor.rs:421–428`
- **Evidence**:
  ```rust
  // supervisor.rs:130-141
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
  In all three error/crash exit transitions, `state.generation` is NOT incremented (`state.generation += 1` is absent).
- **Impact**: Invariant A9 states: *"Generation fencing to prevent zombie / orphaned processes or stale status overwrite."* When an owned server crashes or times out, external observers (Python worker, monitoring threads) query `status()` and observe a state change to `Failed`, but the `generation` counter remains identical to the previous `ReadyOwned` generation. Any async task relying on generation fencing to discard stale status updates will treat the failure as having occurred in the prior epoch or fail to detect the state epoch boundary.

### 3.3 Finding RS-02 (CONFIRMED / BLOCKER): Missing `Stopping` Guard in `ensure_ready` Permits State Overwrites and Orphaned Processes
- **Location**: `runtime_supervisor/src/supervisor.rs:168–275`, `supervisor.rs:485–487`
- **Evidence**:
  When `stop()` is invoked:
  1. `state.state = LifecycleState::Stopping` (line 473).
  2. `let mut proc_opt = state.process.take(); drop(state);` (lines 474–478).
  3. `proc.wait_timeout(timeout)` begins, which can block for up to 10 seconds (lines 480–483).
  4. Concurrently, a worker thread invokes `ensure_ready`.
  5. In `ensure_ready`, lines 173–270 evaluate:
     - `state == ReadyOwned`? False.
     - `state == ReadyAdopted`? False.
     - `state == Starting`? False.
     - **There is NO branch for `state == Stopping`!**
  6. Line 271 executes unconditionally:
     ```rust
     state.generation += 1;
     let my_gen = state.generation;
     state.state = LifecycleState::Starting;
     ```
  7. `ensure_ready` spawns a brand new process $P_2$ and brings it to `ReadyOwned`.
  8. Now `stop()` finishes `wait_timeout` on the old process $P_1$, re-acquires the lock, and executes:
     ```rust
     // supervisor.rs:485-487
     let mut state = self.state.lock().unwrap();
     state.state = LifecycleState::Stopped;
     self.condvar.notify_all();
     ```
- **Impact**: `stop()` unconditionally overwrites `state.state` from `ReadyOwned` (or `Starting`) back to `Stopped` without checking `if state.generation == my_gen`! The newly spawned process $P_2$ continues running in the background as an untracked zombie/orphan, while `RuntimeSupervisor.status()` reports `state: "stopped"`.

### 3.4 Finding RS-03 (CONFIRMED / BLOCKER): `restart()` Does Not Await Process Exit Before Spawning (Port Contention & False Re-adoption Race)
- **Location**: `runtime_supervisor/src/supervisor.rs:448–467`
- **Evidence**:
  ```rust
  // supervisor.rs:448-466
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
- **Impact**:
  1. `restart()` invokes `proc.terminate()`, which calls Windows `TerminateProcess` asynchronously.
  2. Unlike `stop()`, `restart()` **never calls `proc.wait()` or `proc.wait_timeout()`**!
  3. `proc` is dropped immediately, detaching the handle in the OS.
  4. `self.ensure_ready()` is called immediately on line 459.
  5. In `ensure_ready`, line 286 calls `self.health_checker.check_compatible(&self.base_url, Duration::from_millis(500))`.
  6. **Race condition 1 (False re-adoption)**: If the old server process has not finished dying and its socket remains open, `check_compatible` gets HTTP 200 and immediately transitions to `ReadyAdopted` (line 292), adopting the dying process instead of restarting!
  7. **Race condition 2 (Port Collision)**: If `check_compatible` fails but the terminating process has not released port 9379/8080 in the Windows kernel, the new child process is spawned at line 312 and crashes immediately with `WSAEADDRINUSE` (10048).

### 3.5 Finding RS-04 (CONFIRMED / BLOCKER): Concurrent Conflicting `ensure_ready` Calls Cause Ping-Pong Livelock
- **Location**: `runtime_supervisor/src/supervisor.rs:223–269`, `supervisor.rs:314–325`
- **Evidence**:
  1. Thread 1 calls `ensure_ready` with config $C_1$. State becomes `Starting`, `generation = 1`. Thread 1 drops mutex and calls `process_driver.spawn(C_1)`.
  2. While Thread 1 is inside `spawn`, Thread 2 calls `ensure_ready` with different config $C_2$.
  3. Thread 2 sees `state == Starting` and `active.startup_identity != startup_identity`.
  4. Thread 2 supersedes Thread 1:
     ```rust
     state.generation += 1; // generation becomes 2
     if let Some(mut old_proc) = state.process.take() { let _ = old_proc.terminate(); }
     ```
     (Note: `state.process` is `None` because Thread 1 has not returned from spawn yet!)
  5. Thread 2 drops mutex and calls `process_driver.spawn(C_2)`.
  6. Thread 1 finishes spawning $C_1$, re-acquires lock:
     ```rust
     if state.generation != my_gen { // 2 != 1
         if let Ok(mut child) = spawn_result { let _ = child.terminate(); }
         continue 'outer; // Thread 1 loops back!
     }
     ```
  7. Thread 1 loops back to `'outer` with its original config $C_1$.
  8. Thread 1 sees state is `Starting` with $C_2$. It treats $C_2$ as a different config, increments generation to 3, supersedes Thread 2, and spawns $C_1$ again!
  9. Thread 2 finishes spawning $C_2$, sees generation is 3, kills $C_2$, loops back, and supersedes Thread 1!
- **Impact**: Two competing threads with different configurations will endlessly kill each other's processes and increment generations in an unbounded livelock loop.

---

## 4. Process Mechanics & Windows OS Interactions

### 4.1 Process Spawning & Creation Flags
In `runtime_supervisor/src/process.rs:36–55`:
```rust
let mut cmd = Command::new(executable);
cmd.args(args);
for (k, v) in env {
    cmd.env(k, v);
}
#[cfg(windows)]
cmd.creation_flags(CREATE_NO_WINDOW);

cmd.stdout(Stdio::null());
cmd.stderr(Stdio::null());
```
- **Suppression of Console Window**: `CREATE_NO_WINDOW (0x08000000)` prevents flashing console windows on Windows when spawning Python or llama-server.
- **Environment Handling**: Environment map is copied cleanly.

### 4.2 Finding RS-06 (CONFIRMED / DESIGN DETAIL): Absence of Windows Job Objects Permits Process Tree Leaks
- **Location**: `runtime_supervisor/src/process.rs:27–56`
- **Analysis**:
  In Windows, if a parent process terminates abnormally (e.g. NVDA crash, unexpected exit, power failure, or kill via Task Manager), Windows does NOT terminate child processes by default.
  To guarantee process cleanup on Windows:
  The parent process must create a Windows Job Object (`CreateJobObjectW`), configure `JOBOBJECT_EXTENDED_LIMIT_INFORMATION` with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, and assign each spawned child handle to the job object (`AssignProcessToJobObject`).
  Because `runtime_supervisor` does not implement Windows Job Objects:
  1. Any unexpected NVDA crash leaves `python.exe` (LiteRT-LM) or `llama-server.exe` running in the background.
  2. The orphan process holds port 9379/8080 and GPU VRAM.
  3. When NVDA is restarted, the new supervisor cannot bind the port and is forced into the adopted state or fails to start.
  4. Furthermore, `OsProcessHandle::terminate()` calls `Child::kill()`, which invokes `TerminateProcess` strictly on the single process handle. If `llama-server` or `litert-lm` spawned helper subprocesses (such as CUDA/compiler workers or multiprocessing children), those grandchildren are leaked.

### 4.3 Finding RS-07 (CONFIRMED / DESIGN DETAIL): Immediate Forceful Kill (`TerminateProcess`) Disregards Documented Graceful Teardown
- **Location**: `runtime_supervisor/src/process.rs:76–80`, `runtime_supervisor/src/supervisor.rs:480–484`
- **Analysis**:
  Documentation in `runtime_supervisor/src/lib.rs:122` and `addon/.../providers/runtime/server.py:730` states:
  *"Stop the server process gracefully, then forcefully if needed."*
  In `process.rs`:
  ```rust
  fn terminate(&mut self) -> Result<(), String> {
      let _ = self.child.kill();
      Ok(())
  }
  ```
  On Windows, `std::process::Child::kill()` immediately calls `TerminateProcess(hProcess, 1)`.
  There is zero graceful teardown attempt:
  - No `GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT, pid)` or `SetConsoleCtrlHandler`.
  - No HTTP `/exit` or `/shutdown` endpoint invocation.
  - Abrupt termination risks data corruption for memory-mapped GGUF files (`MapViewOfFile`), corrupting KV caches or embedding caches, and leaves GPU device memory deallocation up to the graphics driver.
  - Furthermore, `stop()` calls `proc.terminate()` first, and *then* calls `proc.wait_timeout(timeout)` on an already killed process!

### 4.4 Finding RS-08 (CONFIRMED / DESIGN DETAIL): Complete Discard of `stderr` Prevents Failure Diagnostics
- **Location**: `runtime_supervisor/src/process.rs:44–45`
- **Analysis**:
  ```rust
  cmd.stdout(Stdio::null());
  cmd.stderr(Stdio::null());
  ```
  When `litert-lm` or `llama-server` crashes during startup (for example, missing `cublas64_12.dll`, invalid GGUF architecture, out of VRAM, or bad CLI flag):
  All console error output is redirected to `NUL`.
  The supervisor only knows: `server process exited unexpectedly with code 1` (or Windows error code `3221225781` / `0xC0000135` STATUS_DLL_NOT_FOUND).
  The user and developers are left completely blind to the cause.
  `stderr` should be captured into a fixed-size ring buffer (e.g. 64 KB) and included in `state.last_error`.

---

## 5. Startup Identity & Process Adoption Audit

### 5.1 Endpoint Compatibility vs. Health Checking
In `runtime_supervisor/src/health.rs:9–64`:
- `check_health`: Queries `GET /v1/models` (fallback `GET /models`). Returns true if HTTP status == 200.
- `check_compatible`: Queries `GET /v1/models` (fallback `GET /models`). Verifies HTTP status == 200 AND JSON body contains top-level key `"data"` or `"models"`.

### 5.2 Finding RS-05 (CONFIRMED / LIKELY): Adopted Server Configuration Trap & Model Identity Blindness
- **Location**: `runtime_supervisor/src/health.rs:32–63`, `runtime_supervisor/src/supervisor.rs:199–221, 284–308`
- **Analysis**:
  1. **Blind Adoption**: `check_compatible` does NOT accept or verify `expected_model: Option<&str>`. If an unrelated server (or mock server, or a llama-server running `qwen-2.5-coder`) is already listening on port 9379/8080 when NVDA requests `gemma-2-2b-it`, `check_compatible` returns `true`. The supervisor adopts it and falsely claims it is running `gemma-2-2b-it` (`s.running_model = running_model`).
  2. **Configuration Trap**: When a server is in `LifecycleState::ReadyAdopted`, `ensure_ready` (lines 199–221) simply checks `self.health_checker.check_health(...)`. If healthy, it returns `Ok(RuntimeStatus)` immediately without checking `startup_identity`!
  3. If the user subsequently changes the configured model, context window, or thread count, and calls `ensure_ready` or `restart()`:
     - `restart()` has no process handle (`state.process == None`), so the running process is never stopped.
     - `ensure_ready` re-probes port 9379/8080, finds the old adopted server still responding, and re-adopts it!
     - **The user's configuration change is silently ignored forever.**
  4. **Remedy**:
     - `check_compatible` must inspect the model list returned in `{"data": [{"id": ...}]}` and verify that `expected_model` is present.
     - The supervisor must query the OS network table (`GetExtendedTcpTable` on Windows) to discover the actual PID listening on `host:port`.
     - With the adopted PID discovered, the supervisor can open a process handle with `PROCESS_TERMINATE` rights, allowing `restart()` and `stop()` to terminate an adopted server cleanly when configuration changes.

---

## 6. PyO3 Boundary & Python Worker Interaction

### 6.1 GIL Release Audit
In `runtime_supervisor/src/lib.rs:54–146`:
- `status()` and `matches_startup_configuration()`: Execute non-blocking in-memory mutex reads and `try_wait` syscalls. They do not block and can be safely called on any thread (including NVDA's main thread).
- `ensure_ready`, `restart`, `stop`, `shutdown`, `adopt`: All wrap internal execution in `py.allow_threads(move || { ... })`.
- **Verdict**: GIL release is **CONFIRMED** correct. No blocking network I/O, process wait, or condvar wait is performed while holding Python's GIL.

### 6.2 Finding RS-09 (CONFIRMED / DESIGN DETAIL): Untyped PyO3 Error Mapping Compels Fragile String Parsing
- **Location**: `runtime_supervisor/src/lib.rs:90, 119, 129, 136, 144`
- **Analysis**:
  All errors from `core` are converted via `.map_err(PyRuntimeError::new_err)`.
  In `addon/.../providers/runtime/llama_server.py:384–387`:
  ```python
  except RuntimeError as exc:
      if "exited before becoming ready" in str(exc) or "exited unexpectedly" in str(exc):
          raise LlamaServerError("llama-server exited before becoming ready") from exc
      raise LlamaServerError(...)
  ```
  Python code is forced to perform fragile string scraping on exception text.
  PyO3 should define a native exception hierarchy:
  - `RuntimeSupervisorError(Exception)`
    - `ReadinessTimeoutError`
    - `ProcessCrashError(exit_code, stderr)`
    - `IncompatibleEndpointError`
    - `PortInUseError`

### 6.3 Finding RS-10 (CONFIRMED / BLOCKER): Duplicate Test Shims in Production Modules Violate Invariant A7
- **Location**:
  - `addon/globalPlugins/AI-assistant/providers/runtime/server.py:322–415` (`_TestShimSupervisor`)
  - `addon/globalPlugins/AI-assistant/providers/runtime/llama_server.py:191–258` (`_LlamaTestShimSupervisor`)
- **Analysis**:
  Because pure-Python tests lacked the compiled `runtime_supervisor` extension when running outside full build environments, developers duplicated the entire supervisor state machine in Python directly inside production modules.
  `server.py` checks `if _run_litert_cli is not _real_run_litert_cli:` to switch between native supervisor and `_TestShimSupervisor`.
  This directly violates Invariant A7 (*"Native supervisor as single authoritative owner of runtime mechanics"*). Production code must never harbor unverified shadow supervisors. Test doubles belong in test fixtures or mock injection ports.

### 6.4 Finding RS-11 (CONFIRMED / DESIGN DETAIL): Python 3.14 Environment Requires ABI3 Forward Compatibility Flag
- **Location**: `runtime_supervisor/Cargo.toml:11`, `scripts/build.py:326`
- **Analysis**:
  When running `cargo test --manifest-path runtime_supervisor/Cargo.toml` on environments where Python 3.14 preview is registered, PyO3 0.23 fails with:
  `error: the configured Python interpreter version (3.14) is newer than PyO3's maximum supported version (3.13)`.
  In `scripts/build.py:326`, `env["PYO3_USE_ABI3_FORWARD_COMPATIBILITY"] = "1"` is already set. However, developers running `cargo test` directly in shell must set `$env:PYO3_USE_ABI3_FORWARD_COMPATIBILITY="1"` or `PYO3_PYTHON`.

---

## 7. Invariant Conformance Evaluation (A7–A10, A25–A26)

### Invariant A7: Native supervisor as single authoritative owner of runtime mechanics
- **Status**: **FAILED (BLOCKED by RS-10 and Python lifecycle hooks)**
- **Findings**:
  1. `_TestShimSupervisor` in `server.py` and `_LlamaTestShimSupervisor` in `llama_server.py` implement duplicate Python supervisors.
  2. `plugin/background.py` still runs background threads (`_on_litert_server_config_changed`, `_on_llama_server_config_changed`) attempting to orchestrate restarts and shutdowns from NVDA space.
  3. `server.py` runs `subprocess.run` directly for `litert-lm import`.

### Invariant A8: Immutable runtime specifications
- **Status**: **PARTIAL (DESIGN DETAIL)**
- **Findings**:
  Rust supervisor receives `startup_identity` as an opaque string hash generated by Python. It does not validate or store the typed specification DTO (`RuntimeSpec`) natively.

### Invariant A9: Generation fencing to prevent zombie / orphaned processes or stale status overwrite
- **Status**: **FAILED (BLOCKED by RS-01, RS-02, RS-03, RS-04)**
- **Findings**:
  1. Crash exits and timeouts do not increment generation counter (RS-01).
  2. `stop()` overwrites newer generations without generation validation (RS-02).
  3. `restart()` races port release without generation fence on port unbinding (RS-03).
  4. Concurrent differing startups ping-pong livelock generations (RS-04).

### Invariant A10: Clean PyO3 interface to Python / worker
- **Status**: **PARTIAL (DESIGN DETAIL RS-09)**
- **Findings**:
  PyO3 interface releases GIL correctly and exposes non-blocking status queries, but lacks typed exception classes and progress streaming callbacks.

### Invariants A25–A26: Process isolation & Native authority within Worker boundary
- **Status**: **FAILED (BLOCKED by RS-13)**
- **Findings**:
  At HEAD (`ced1cbc`), `RuntimeSupervisor` runs inside the NVDA process (`nvda.exe`). All child processes are spawned directly from NVDA. In the target topology, ownership must move wholly into the Worker process (`nvda_ai_worker.exe` / pure Python worker).

---

## 8. Complete Classified Findings Table

| ID | Title | File Path & Lines at HEAD (`ced1cbc`) | Classification | Impact |
|---|---|---|---|---|
| **RS-01** | Generation counter not incremented on child crash or timeout | `runtime_supervisor/src/supervisor.rs:130–141, 358–370, 421–428` | **CONFIRMED, BLOCKER** | Stale generation fencing; status observers cannot detect failure epoch. |
| **RS-02** | Missing `Stopping` guard in `ensure_ready` causes state overwrite and orphan child processes | `runtime_supervisor/src/supervisor.rs:168–275, 485–487` | **CONFIRMED, BLOCKER** | `stop()` overwrites `ReadyOwned` to `Stopped`; spawned process leaked as zombie. |
| **RS-03** | `restart()` does not await process exit before immediate re-launch | `runtime_supervisor/src/supervisor.rs:448–467` | **CONFIRMED, BLOCKER** | Causes false re-adoption of dying process or socket bind collision (`WSAEADDRINUSE`). |
| **RS-04** | Concurrent conflicting `ensure_ready` calls enter ping-pong livelock | `runtime_supervisor/src/supervisor.rs:223–269, 314–325` | **CONFIRMED, BLOCKER** | Threads with different configs repeatedly abort and restart each other indefinitely. |
| **RS-05** | Adopted server configuration trap & model identity blindness | `runtime_supervisor/src/health.rs:32–63`, `supervisor.rs:199–221, 284–308` | **CONFIRMED, LIKELY** | Unrelated model adopted blindly; subsequent config changes silently ignored. |
| **RS-06** | Absence of Windows Job Objects permits process tree leaks | `runtime_supervisor/src/process.rs:27–56, 76–80` | **CONFIRMED, DESIGN DETAIL** | Abnormal NVDA termination leaks running server and GPU memory. |
| **RS-07** | Immediate forceful kill (`TerminateProcess`) bypasses graceful teardown | `runtime_supervisor/src/process.rs:76–80`, `supervisor.rs:480–484` | **CONFIRMED, DESIGN DETAIL** | Risk of memory-mapped model file corruption and GPU driver hang. |
| **RS-08** | Complete discard of child `stderr` output hides crash diagnostics | `runtime_supervisor/src/process.rs:44–45` | **CONFIRMED, DESIGN DETAIL** | Missing DLLs or CUDA errors cannot be diagnosed; only exit code available. |
| **RS-09** | Generic PyO3 `RuntimeError` mapping forces fragile string scraping | `runtime_supervisor/src/lib.rs:90, 119, 129, 136, 144` | **CONFIRMED, DESIGN DETAIL** | Python callers must grep error messages to distinguish failure types. |
| **RS-10** | Duplicate Python test shims in production modules violate Invariant A7 | `server.py:322–415`, `llama_server.py:191–258` | **CONFIRMED, BLOCKER** | Unverified parallel supervisor implementations live in production codebase. |
| **RS-11** | Python 3.14 build environment requires ABI3 forward compatibility flag | `runtime_supervisor/Cargo.toml:11`, `scripts/build.py:326` | **CONFIRMED, DESIGN DETAIL** | `cargo test` fails out-of-the-box on systems with Python 3.14 installed. |
| **RS-12** | GIL release verified correct across all blocking operations | `runtime_supervisor/src/lib.rs:80–89, 109–118, 128–130, 135–136, 143–144` | **CONFIRMED, DESIGN DETAIL** | NVDA main thread is protected; long-running operations do not block Python. |
| **RS-13** | Runtime supervisor located in NVDA process rather than Worker boundary | `plugin/background.py:51–112`, `server.py:544`, `llama_server.py:291` | **CONFIRMED, BLOCKER** | Violates Invariants A25–A26 and target process topology. |

---

## 9. Pre-Implementation Recommendations & Target Architecture Plan

### 9.1 Rust Supervisor Fixes (Slice 0 & Pre-Implementation)
Before moving `runtime_supervisor` into the Worker boundary (Slices 6 & 7), the following fixes must be applied to `runtime_supervisor/src/`:
1. **Fix Generation Monotonicity (RS-01)**:
   In `refresh_process_state_locked`, poll exit handling, and readiness timeout, always increment `state.generation += 1`.
2. **Add `Stopping` / `Restarting` Guards to `ensure_ready` (RS-02, RS-03)**:
   If `state.state == LifecycleState::Stopping`, `ensure_ready` must wait on `condvar` until `state.state == LifecycleState::Stopped` before beginning a new startup sequence. In `stop()`, check `if state.generation == my_gen` before assigning `LifecycleState::Stopped`.
3. **Await Process Teardown in `restart()` (RS-03)**:
   `restart()` must call `proc.wait_timeout(timeout)` before calling `ensure_ready()`, and poll the socket until port binding is released.
4. **Serialize Conflicting Startups (RS-04)**:
   When `ensure_ready` encounters an in-flight `Starting` state with a differing configuration, it must wait on `condvar` for the in-flight startup to conclude (or abort), rather than immediately bumping generations and triggering livelock.
5. **Windows Job Object Integration (RS-06)**:
   Use `windows-sys` or `winapi` in `OsProcessDriver` to associate spawned child processes with a job object configured with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.
6. **Capture `stderr` Ring Buffer (RS-08)**:
   Use an asynchronous pipe reader thread to capture the last 64 KB of `stderr` into an in-memory buffer, appended to `last_error` on exit.
7. **Typed PyO3 Exceptions (RS-09)**:
   Expose `ReadinessTimeoutError` and `ProcessCrashError` classes in `runtime_supervisor`.

### 9.2 Migration to Worker Boundary (Slices 6, 7, 8)
1. **Slice 6 (LiteRT Runtime Ownership Moved to Worker)**:
   Move `RuntimeSupervisor("litert-lm")` out of `addon/.../providers/runtime/server.py` into the pure-Python / native Worker process.
2. **Slice 7 (llama.cpp Runtime Ownership Moved to Worker)**:
   Move `RuntimeSupervisor("llama-server")` out of `addon/.../providers/runtime/llama_server.py` into the Worker process.
3. **Slice 8 (Removal of Obsolete NVDA-Side Runtime Threading)**:
   Delete `_TestShimSupervisor` and `_LlamaTestShimSupervisor` from production code. Delete `_on_litert_server_config_changed`, `_restart_litert_server_worker`, `_on_llama_server_config_changed`, and `shutdown_llama_servers` from `plugin/background.py`. NVDA communicates solely via typed Worker IPC requests (`EnsureRuntimeReady`, `StopRuntime`, `GetRuntimeStatus`).
