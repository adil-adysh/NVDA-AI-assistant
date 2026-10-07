# Adversarial Challenge Report: Milestone 1 (Slice 0: Rust Runtime Supervisor Concurrency Hardening)

**Challenger**: Empirical Challenger 2 (`m1_challenger_2`)  
**Scope**: RS-03 (Restart Socket Quiescence & Dying Server Adoption Prevention) and RS-04 (Startup Livelock Mitigation under Competing Configurations)  
**Date**: 2026-10-04  
**Verdict**: **APPROVE**  

---

## Challenge Summary

**Overall risk assessment**: **LOW**  
The concurrency hardening introduced in `runtime_supervisor` (specifically RS-03 and RS-04) was subjected to rigorous empirical attack vectors including delayed termination adoption traps, hung process termination timeouts, massive concurrent contention (up to 20 threads), and alternating configuration stress testing. The implementation proved exceptionally resilient, robustly maintaining epoch generation monotonicity, preventing premature adoption of dying server processes, completely eliminating preemption ping-pong livelocks, and bounding child process spawning to strictly non-runaway levels.

---

## Challenges

### [Medium] Challenge 1: Premature Adoption of Dying Server during Asynchronous Teardown (RS-03)

- **Assumption challenged**: That calling `ensure_ready()` after initiating process termination cannot erroneously discover the dying process's active socket endpoint and prematurely adopt it as `ReadyAdopted`.
- **Attack scenario**: In prior HEAD (`ced1cbc`), `restart()` invoked `proc.terminate()` and immediately called `ensure_ready()`. If the child process took 50–100ms to exit, the lingering HTTP server on the port responded to `check_compatible()`, tricking `ensure_ready()` into transitioning to `ReadyAdopted` instead of spawning a replacement. Shortly thereafter, the OS kernel killed the dying process, leaving the supervisor holding a zombie `ReadyAdopted` state.
- **Empirical Stress Test**: Constructed a dynamic test harness (`test_adversarial_restart_does_not_adopt_dying_server_when_alive_is_delayed`) where `FakeProcessHandle::wait_timeout()` simulated a 60ms delay before terminating the process, and `HealthChecker::check_compatible()` dynamically returned `true` whenever `alive` was `true`. Invoked `restart()` with a new configuration.
- **Observed Behavior**: `restart()` in `runtime_supervisor/src/supervisor.rs:520–553` synchronously blocked on `old_proc.wait_timeout(drain_timeout)` until the process exited (`alive` transitioned to `false`), followed by active socket quiescence polling via `!health_checker.check_health()`. Only then did `ensure_ready()` execute.
- **Result**: `status().state == "ready_owned"`, `!status().is_adopted`, and `spawns == 2`. Premature adoption was completely thwarted. **PASS**.
- **Blast radius if failed**: Add-on would permanently lose model inference capabilities whenever a model config was changed, requiring manual NVDA restart.
- **Mitigation verified**: The 5-phase sequential teardown in `supervisor.rs` guarantees process termination and socket release prior to replacement spawn.

---

### [High] Challenge 2: Competing Configurations Mutual Preemption Livelock (RS-04)

- **Assumption challenged**: That competing concurrent callers to `ensure_ready()` with differing model configurations (e.g. `model-A` vs `model-B`) do not enter an infinite loop, starve callers, or trigger a runaway process spawning storm.
- **Attack scenario**: In prior HEAD (`ced1cbc`), `ensure_ready()` checked `if state.state == Starting` and, if the incoming config differed from the in-flight config, immediately killed the in-flight process and spawned a replacement. Two competing callers alternating requests would endlessly preempt and terminate each other's processes in a microsecond ping-pong loop, never allowing either process to reach `ReadyOwned`.
- **Empirical Stress Test**: 
  1. Ran `test_concurrent_ensure_ready_differing_configs_no_livelock` with two concurrent threads competing with `model-A` and `model-B`.
  2. Executed a 10-thread stress harness (`test_10_concurrent_threads_two_competing_configs_bounded_spawns`) with alternating competing configurations.
  3. Executed a 20-thread deduplication stress harness (`test_20_concurrent_threads_same_config_spawn_exactly_once`).
- **Observed Behavior**:
  - In `supervisor.rs:266–318`, competing callers seeing `LifecycleState::Starting` wait on `self.condvar` regardless of configuration. The in-flight process is permitted to complete its startup sequence without interruption.
  - In the 2-thread test, exactly 2 processes were spawned (one for model-A, one for model-B); both threads completed with `Ok(RuntimeStatus)`.
  - In the 20-thread identical config test, exactly 1 process was spawned, with all 20 threads deduplicating and returning `Ok`.
  - Under extreme multi-thread config alternation (10 threads), the bounded retry counter `MAX_ATTEMPTS = 5` and exponential backoff (`50ms * 2^attempt`) acted as a robust circuit breaker, ensuring bounded process creation (4 spawns total) and cleanly erroring out starved threads rather than spinning indefinitely.
- **Result**: Zero infinite loops, zero runaway process storms. **PASS**.
- **Blast radius if failed**: High CPU utilization, runaway child process leaks, VRAM exhaustion, and total UI freezing.
- **Mitigation verified**: Condvar wait during `Starting` + sequential `restart()` + `MAX_ATTEMPTS = 5` circuit breaker.

---

### [Medium] Challenge 3: Child Process Hang During Restart Teardown (RS-03)

- **Assumption challenged**: That if an old server process hangs or deadlocks during termination, `restart()` does not launch a rogue replacement process on a colliding port.
- **Attack scenario**: If `proc.terminate()` fails to kill the child, or the child ignores termination and remains running, spawning a replacement would cause port bind collision (`WSAEADDRINUSE`).
- **Empirical Stress Test**: Tested hung process termination (`test_adversarial_restart_process_hang_fails_without_rogue_spawn`) by configuring `wait_timeout()` to simulate an unkillable process exceeding timeout.
- **Observed Behavior**: `supervisor.rs:528–539` detected `Ok(None)` from `wait_timeout()`, incremented `state.generation`, transitioned state to `Failed`, set `last_error`, notified `condvar`, and returned `Err(...)` without calling `ensure_ready()`.
- **Result**: `driver.spawns` remained strictly 1. No rogue replacement process was spawned. **PASS**.

---

## Stress Test Results

| # | Stress Scenario | Expected Behavior | Actual Behavior | Result |
|---|-----------------|-------------------|-----------------|:------:|
| 1 | Standard restart socket teardown (`test_restart`) | Waits for process exit and does not adopt dying server | `proc.wait_timeout` invoked and verified; 2 spawns; `ready_owned` | **PASS** |
| 2 | Competing differing configs (`test_concurrent_ensure_ready_differing_configs_no_livelock`) | Deduplicates in-flight startup; <= 2 spawns | Exactly 2 spawns; both threads Ok; no livelock | **PASS** |
| 3 | Windows Job Object containment (`test_os_process_handle_job_object_containment`) | Child process contained in Win32 Job Object | `IsProcessInJob` syscall returns 1 | **PASS** |
| 4 | Adversarial delayed process exit with dynamic compatibility | Does not adopt dying server even when HTTP responds during teardown | `status.state == ready_owned`, `!status.is_adopted`, `spawns == 2` | **PASS** |
| 5 | Adversarial hung process on restart | Fails restart cleanly without spawning colliding replacement | Returns `Err("failed to terminate")`, `spawns == 1` | **PASS** |
| 6 | 20 concurrent threads with identical config | Exactly 1 process spawned; all 20 threads succeed | `spawns == 1`, 20/20 threads Ok, `ready_owned` | **PASS** |
| 7 | Concurrent `restart()` and `ensure_ready()` race | Both threads coordinate via condvar; no panic or deadlock | Both threads Ok; `spawns <= 3`; `ready_owned` | **PASS** |
| 8 | 10 concurrent threads with alternating configs | Circuit breaker prevents infinite loop; spawns bounded | `spawns == 4`, 8 Ok / 2 circuit-broken, no livelock | **PASS** |

---

## Verification Commands & Output Verification

All required commands were executed directly:

1. `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml -- test_restart`:
   ```text
   running 2 tests
   test tests::test_restart_does_not_adopt_dying_server ... ok
   test tests::test_restart_waits_for_child_process_termination ... ok

   test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 18 filtered out; finished in 0.25s
   ```

2. `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml -- test_concurrent_ensure_ready_differing_configs_no_livelock`:
   ```text
   running 1 test
   test tests::test_concurrent_ensure_ready_differing_configs_no_livelock ... ok

   test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 19 filtered out; finished in 0.20s
   ```

3. `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml -- test_os_process_handle_job_object_containment`:
   ```text
   running 1 test
   test tests::test_os_process_handle_job_object_containment ... ok

   test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 19 filtered out; finished in 0.01s
   ```

4. Full crate test suite (`uv run cargo test --manifest-path runtime_supervisor/Cargo.toml`):
   ```text
   test result: ok. 20 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 1.53s
   ```

5. Repository Verification Gates:
   - `cargo check --manifest-path nvda_ui_host/Cargo.toml`: 0 errors.
   - `uv run ruff check .`: "All checks passed!" (0 errors).
   - `uv run pytest`: 461 passed, 3 deselected in 13.01s (0 failures).

---

## Unchallenged Areas

- **Non-Windows Job Object Containment**: Win32 Job Object containment is guarded by `#[cfg(windows)]`. On Linux/macOS, process containment relies on standard POSIX process hierarchy rather than Job Objects. (Out of scope: NVDA is a Windows-exclusive application).
- **Physical GPU VRAM Out-of-Memory behavior**: Model weight allocation during process spawn depends on external `llama-server` / `litert-lm` binaries; mock drivers were used to simulate child exit codes and startup failures.
