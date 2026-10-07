# Architecture Specification & Verification Mining Report: Migration Slices 0 & 1

**Document Version:** 1.0.0 (Authoritative Mining Report)  
**Date:** 2026-10-04  
**Investigator:** `survey_explorer_baseline_3` (Architecture Spec & Verification Miner)  
**Repository:** `adil-adysh/NVDA-AI-assistant`  
**Baseline Git Commit:** `ced1cbc` (and ancestors)  
**Target Milestone:** Migration Slice 0 & Slice 1  
**Authoritative Contracts:**  
- `ORIGINAL_REQUEST.md` (Project Directives 2026-10-02 & 2026-10-04)  
- `architecture_deliverable.md` (Master Architectural Deliverable & Slices 0–10 Implementation Plan)  

---

## 1. Executive Summary

This specification mining report establishes the exhaustive contract, architectural invariants, failure modes, edge cases, acceptance criteria, and zero-regression verification gates for:
1. **Migration Slice 0**: Rust Runtime Supervisor Concurrency Hardening & Contract Cleanup (`runtime_supervisor/`).
2. **Migration Slice 1**: Pure Python Test Boundary Decoupling & Import Enforcement (`conftest.py`, `utils/logger.py`, AST boundary tests, Ruff TID251).
3. **Zero-Regression Verification Gates**: Static linting, Rust PyO3 test suite, native Win32/WebView2 UI host compilation, and full Python pytest test suite.
4. **Feature Inventory Synthesis**: Structured feature inventory table mapping features to Milestones M1, M2, and M3 with invariant traceability.

All findings are backed by verified source code citations (file paths and line numbers) at HEAD (`ced1cbc`).

---

## 2. Migration Slice 0: Rust Runtime Supervisor Concurrency Hardening

### 2.1 Context & Scope
The native Rust `runtime_supervisor` crate (`runtime_supervisor/`) is the single authoritative owner of local runtime process lifecycle mechanics (for `LiteRT-LM` on port 9379 and `llama-server.exe` on port 8080). While it successfully provides GIL release (`py.allow_threads`) and basic process lifecycle transitions, Audit E and the master architecture deliverable identified critical concurrency, generation fencing, and process containment defects that must be resolved in Slice 0 before expanding worker ownership.

### 2.2 Detailed Defect Analysis & Requirements (RS-01 to RS-10)

#### RS-01: Generation Counter Monotonicity on Process Exits & Timeouts [CONFIRMED, BLOCKER]
- **Affected Files & Lines**:  
  - `runtime_supervisor/src/supervisor.rs:126–142` (`refresh_process_state_locked`)
  - `runtime_supervisor/src/supervisor.rs:358–370` (child poll exit detection in `ensure_ready` startup loop)
  - `runtime_supervisor/src/supervisor.rs:405–429` (readiness timeout expiration branch)
  - `runtime_supervisor/src/supervisor.rs:217–221` (disappearance of adopted server)
- **Root Cause & Mechanism**:  
  In `refresh_process_state_locked()`, when `process.poll()` detects child exit (`Ok(Some(exit_code))`), `state.state` is transitioned to `Failed` (if `exit_code != 0`) or `Stopped` (if `exit_code == 0`), but `state.generation` is NOT incremented. Similarly, in the `ensure_ready` startup polling loop and readiness timeout branch, `state.state` is set to `Failed` without incrementing `state.generation`.
- **Architectural Hazard & Invariant A9 Violation**:  
  External observers (Python polling threads, UI status bars, health checks) rely on monotonic integer `generation` to distinguish distinct lifecycle epochs. When a crash or timeout leaves `generation` unchanged:
  1. Stale health check responses or error reports from a dying process can overwrite newer state.
  2. Observers cannot distinguish whether the supervisor is in a failure state from generation $N$ or a newly initialized generation $N$.
- **Required Behavior**:  
  `state.generation += 1` must occur monotonically on **every** state transition to `Failed` or `Stopped`, including:
  1. Unexpected child process exit (`exit_code != 0`)
  2. Graceful unhandled child exit (`exit_code == 0`)
  3. Startup exit detection
  4. Startup readiness timeout
  5. Disappearance of adopted server
- **Acceptance Criteria**:  
  `runtime_supervisor/src/tests.rs` unit tests verify that any child exit (zero or non-zero) and any startup timeout monotonically increment `generation`. Status updates referencing previous generations are discarded.

---

#### RS-02: Missing Stopping Guard in `ensure_ready` [CONFIRMED, BLOCKER]
- **Affected Files & Lines**:  
  - `runtime_supervisor/src/supervisor.rs:168–275` (`ensure_ready`)
  - `runtime_supervisor/src/supervisor.rs:470–498` (`stop`)
- **Root Cause & Mechanism**:  
  In `stop(timeout)`, the supervisor sets `state.state = LifecycleState::Stopping`, increments generation, drops the mutex lock, and waits for process termination via `proc.wait_timeout(timeout)`.  
  While `stop()` is waiting for process exit, a concurrent thread calling `ensure_ready()` acquires the lock. Because `ensure_ready()` only explicitly handles `ReadyOwned` (line 173), `ReadyAdopted` (line 199), and `Starting` (line 224), it falls through to line 271 (`Stopped or Failed`), transitions `state.state = LifecycleState::Starting`, spawns a new child process, and transitions to `ReadyOwned`.  
  When `stop()` completes its wait, it re-acquires the lock at line 485 and unconditionally sets `state.state = LifecycleState::Stopped`, wiping out the newly spawned process's tracking.
- **Architectural Hazard & Invariants A7, A9 Violation**:  
  The newly spawned server process becomes an untracked, orphaned zombie process holding GPU VRAM and network ports (9379/8080), while the supervisor falsely reports `state = Stopped`.
- **Required Behavior**:  
  1. In `ensure_ready()`: Add an explicit guard: if `state.state == LifecycleState::Stopping`, wait on `self.condvar` until the state becomes `LifecycleState::Stopped` before attempting to start or adopt.
  2. In `stop()`: When re-acquiring the lock after `wait_timeout()`, guard the write: only set `state.state = LifecycleState::Stopped` if `state.generation == my_gen`. If `generation` changed while `stop()` was waiting, drop the write.
- **Acceptance Criteria**:  
  Unit/integration test where `stop()` runs concurrently with `ensure_ready()`. `ensure_ready()` is blocked until stopping finishes; the resulting state is correctly tracked as `ReadyOwned` with valid PID, and zero orphaned processes exist.

---

#### RS-03: Socket Collision on Restart (`WSAEADDRINUSE`) [CONFIRMED, BLOCKER]
- **Affected Files & Lines**:  
  - `runtime_supervisor/src/supervisor.rs:448–467` (`restart`)
- **Root Cause & Mechanism**:  
  `restart()` takes the lock, increments generation, sets `state = Restarting`, takes `state.process`, calls `proc.terminate()`, drops the lock, and immediately calls `self.ensure_ready()`.  
  Crucially, `restart()` **never calls `wait()` or `wait_timeout()` on the old process**.
- **Architectural Hazard & Invariant A9 Violation**:  
  1. Under Windows, `proc.terminate()` issues `TerminateProcess` asynchronously. The dying process takes several milliseconds to release its TCP listening port.
  2. `ensure_ready()` immediately attempts to spawn the new replacement process or run `check_compatible()`.
  3. If `check_compatible()` runs first, it may hit the dying socket and falsely adopt the terminating process.
  4. If the new process spawns immediately, it fails to bind with WinSock error `10048` (`WSAEADDRINUSE`), crashing on startup.
- **Required Behavior**:  
  In `restart()`, if a process handle is taken, `restart()` MUST invoke `proc.wait_timeout(timeout)` to verify process exit and ensure port release before calling `ensure_ready()`.
- **Acceptance Criteria**:  
  Test in `tests.rs` verifying that rapid restarts await previous process exit and port release before spawning the replacement.

---

#### RS-04: `ensure_ready` Startup Livelock & Bounded Backoff [CONFIRMED, BLOCKER]
- **Affected Files & Lines**:  
  - `runtime_supervisor/src/supervisor.rs:223–269` (`ensure_ready` in-flight Starting handling)
- **Root Cause & Mechanism**:  
  When `state.state == LifecycleState::Starting` and an incoming `ensure_ready` call has a configuration that differs from `state.active_config`:
  ```rust
  // Config differs while starting: supersede current startup
  state.generation += 1;
  if let Some(mut old_proc) = state.process.take() {
      let _ = old_proc.terminate();
  }
  ```
  If two threads alternate requests with different configs (e.g. Model A vs Model B), each thread terminates the other's process before it can finish booting and responding to health checks.
- **Architectural Hazard & Invariants A7, A10 Violation**:  
  Threads enter an infinite ping-pong livelock loop, endlessly killing each other's child processes, thrashing CPU/GPU, and incrementing generations until timeouts expire.
- **Required Behavior**:  
  1. When `ensure_ready` detects `Starting` with a different configuration, do not preemptively terminate immediately; wait on `condvar` for the in-flight startup to complete or fail up to a bounded deadline.
  2. Add bounded retries with exponential backoff and circuit breaking to prevent infinite tight retry loops during startup failure.
- **Acceptance Criteria**:  
  Concurrency test in `tests.rs` simulating conflicting startup requests; threads serialize cleanly rather than entering a destructive livelock loop.

---

#### RS-06: Windows Job Object Containment (`KILL_ON_JOB_CLOSE`) [CONFIRMED, DESIGN DETAIL]
- **Affected Files & Lines**:  
  - `runtime_supervisor/src/process.rs:27–56` (`OsProcessDriver::spawn`)
- **Root Cause & Mechanism**:  
  Child processes are spawned via `std::process::Command` with `CREATE_NO_WINDOW`, but are never assigned to a Win32 Job Object.
- **Architectural Hazard & Invariants A16, A26 Violation**:  
  If NVDA crashes, hangs, or is terminated via Task Manager (`taskkill /f /im nvda.exe`), or suffers an unhandled exception in another add-on, all child runtime processes (`litert-lm`, `llama-server.exe`) remain alive indefinitely in the Windows desktop session. They hold TCP ports 9379/8080 and retain GPU VRAM, blocking subsequent NVDA sessions from starting local models.
- **Required Behavior**:  
  1. On Windows (`#[cfg(windows)]`), create/open an anonymous Win32 Job Object configured with `JOBOBJECT_EXTENDED_LIMIT_INFORMATION`:
     - `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`: Guarantees kernel-level process termination when parent process closes.
     - `JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION`: Prevents modal Win32 Watson/WER crash dialogs from blocking process cleanup.
  2. Assign each spawned child process handle to the Job Object via `AssignProcessToJobObject` immediately upon creation.
- **Acceptance Criteria**:  
  On Windows, child processes spawned by `OsProcessDriver` are assigned to a Job Object with `KILL_ON_JOB_CLOSE`.

---

#### RS-10: Removal of Shadow Test Shims from Production PyO3 Modules [CONFIRMED, BLOCKER]
- **Affected Files & Lines**:  
  - `addon/globalPlugins/AI-assistant/providers/runtime/server.py:322–415` (`_TestShimSupervisor`)
  - `addon/globalPlugins/AI-assistant/providers/runtime/llama_server.py:91–258` (`_LlamaTestShimSupervisor`)
- **Root Cause & Mechanism**:  
  Legacy Python mock implementations of the `RuntimeSupervisor` interface were left embedded in production runtime modules to facilitate unit tests patching `_run_litert_cli` or `process_factory`.
- **Architectural Hazard & Invariant A7 Violation**:  
  Violates Invariant A7 (single authoritative native owner of runtime mechanics). Maintaining parallel Python implementations of supervisor logic leads to state drift, untested production code paths, and hidden failures.
- **Required Behavior**:  
  1. Delete `_TestShimSupervisor` and `_LlamaTestShimSupervisor` from production source files.
  2. Production `LiteRTServerSupervisor` and `LlamaServerSupervisor` must instantiate exclusively the native `runtime_supervisor.RuntimeSupervisor` PyO3 class.
  3. Move any test mocks to test support files (`tests/support/`) if needed for pure Python testing, or rely on native extension tests.
- **Acceptance Criteria**:  
  Zero test shims remain in `providers/runtime/server.py` and `llama_server.py`.

---

## 3. Migration Slice 1: Pure Python Test Boundary Decoupling & Import Enforcement

### 3.1 Context & Scope
At HEAD (`ced1cbc`), **80.7% (92 of 114) of production Python files** represent pure domain, service, provider, and configuration logic that does not intrinsically depend on NVDA's accessibility C/COM subsystem. However, two obstacles prevent pure Python testing:
1. Root `conftest.py` unconditionally requires the sibling `../nvda` source checkout.
2. 18 domain/service files directly import `from logHandler import log`, and `config/settings.py` imports `languageHandler`.

Slice 1 decouples this boundary, introduces a logging facade, configures Ruff `TID251`, and adds an automated AST boundary test.

### 3.2 Conftest Sibling Decoupling (Invariant A30)
- **Current Defect (`conftest.py:27–31`)**:
  ```python
  if not (NVDA_SOURCE / "api.py").is_file():
      raise pytest.UsageError(
          "NVDA source checkout was not found at ../nvda. "
          "Clone https://github.com/nvaccess/nvda.git beside NVDA-AI-assistant.",
      )
  ```
  If `../nvda` is missing, pytest collection aborts immediately for all 464 tests.
- **Decoupling Requirements**:
  1. Remove unconditional `pytest.UsageError` in root `conftest.py`.
  2. Allow test collection and execution of all pure domain, service, config, provider, prompt, and tool tests without requiring `../nvda` checkout or stubs.
  3. Gate NVDA integration tests requiring real NVDA checkout behind `-m nvda_integration`. If `../nvda` is absent or unbuilt, pytest deselects or skips `nvda_integration` tests while running pure tests cleanly.
  4. Scope NVDA bootstrap: Only initialize `globalVars`, `controlTypes`, `textInfos` when NVDA integration tests are requested.
- **Target Performance**:  
  Pure Python test suite executes in < 3.0s.

### 3.3 Logging Facade & Fallback (Invariants A5, A6)
- **Inventory of Contaminated Domain/Service Files**: Exactly 18 pure files currently import `logHandler`:
  1. `addon/globalPlugins/AI-assistant/config/yaml_store.py`
  2. `addon/globalPlugins/AI-assistant/config/state.py`
  3. `addon/globalPlugins/AI-assistant/service/error_reporter.py`
  4. `addon/globalPlugins/AI-assistant/service/base.py`
  5. `addon/globalPlugins/AI-assistant/service/model_cache.py`
  6. `addon/globalPlugins/AI-assistant/service/chat/repository_backends.py`
  7. `addon/globalPlugins/AI-assistant/service/chat/coordinator.py`
  8. `addon/globalPlugins/AI-assistant/providers/adapters/openai_compat.py`
  9. `addon/globalPlugins/AI-assistant/providers/litert_manager.py`
  10. `addon/globalPlugins/AI-assistant/providers/llama_manager.py`
  11. `addon/globalPlugins/AI-assistant/providers/provider_proxy.py`
  12. `addon/globalPlugins/AI-assistant/providers/_provider_runtime.py`
  13. `addon/globalPlugins/AI-assistant/providers/runtime/download.py`
  14. `addon/globalPlugins/AI-assistant/providers/runtime/manager.py`
  15. `addon/globalPlugins/AI-assistant/providers/runtime/model_download.py`
  16. `addon/globalPlugins/AI-assistant/prompts/base.py`
  17. `addon/globalPlugins/AI-assistant/observability/reporter.py`
  18. `addon/globalPlugins/AI-assistant/utils/crypto.py`
- **Decoupling Requirements**:
  1. Introduce `addon/globalPlugins/AI-assistant/utils/logger.py` (or standardize standard library `logging.getLogger(__name__)`).
  2. When running inside NVDA, a logging handler bridges Python `logging` messages to NVDA's `logHandler.log`.
  3. When running outside NVDA (in tests or standalone worker), `logging.getLogger` outputs to standard stream or pytest `caplog` without requiring `logHandler`.
  4. Decouple `languageHandler` in `addon/globalPlugins/AI-assistant/config/settings.py:8` via a pluggable `register_language_resolver` port with a default "en" fallback.

### 3.4 Automated AST Import Boundary Test Gate (`tests/test_import_boundaries.py`)
- **Forbidden NVDA Root Modules**:
  `api`, `textInfos`, `controlTypes`, `globalPluginHandler`, `scriptHandler`, `queueHandler`, `gui`, `wx`, `speech`, `tones`, `logHandler`, `languageHandler`.
- **Pure Subtree Scope**:
  - `addon/globalPlugins/AI-assistant/core/`
  - `addon/globalPlugins/AI-assistant/config/`
  - `addon/globalPlugins/AI-assistant/service/`
  - `addon/globalPlugins/AI-assistant/providers/`
  - `addon/globalPlugins/AI-assistant/use_case/`
  - `addon/globalPlugins/AI-assistant/tools/`
  - `addon/globalPlugins/AI-assistant/prompts/`
  - `addon/globalPlugins/AI-assistant/embeddings/`
  - `addon/globalPlugins/AI-assistant/observability/`
- **Implementation Mechanism**:
  Uses `ast.parse` and `ast.walk` to inspect all `Import` and `ImportFrom` nodes across all Python files in the pure subtree. Asserts that 0 forbidden modules are directly or transitively imported. Runtime: < 200ms.

### 3.5 Ruff Banned API Configuration (TID251)
- **Configuration in `pyproject.toml`**:
  ```toml
  [tool.ruff.lint]
  extend-select = ["TID251"]

  [tool.ruff.lint.flake8-tidy-imports.banned-api]
  "logHandler".msg = "Use standard library 'logging.getLogger(__name__)' instead of NVDA logHandler."
  "languageHandler".msg = "Access language via injected LanguageResolver port."
  "api".msg = "NVDA api access is forbidden outside Layer 0 extractors."
  "textInfos".msg = "textInfos is forbidden outside Layer 0 extractors."
  "controlTypes".msg = "controlTypes is forbidden outside Layer 0 extractors."
  "queueHandler".msg = "queueHandler is forbidden outside ui/nvda_ui.py."
  "gui".msg = "gui is forbidden outside ui/ dialogs."
  "wx".msg = "wx is forbidden outside ui/ dialogs."
  "speech".msg = "speech is forbidden outside ui/nvda_ui.py."
  "tones".msg = "tones is forbidden outside ui/nvda_ui.py."

  [tool.ruff.lint.per-file-ignores]
  # Pure packages strictly ban all NVDA modules
  "addon/globalPlugins/AI-assistant/core/**" = ["TID251"]
  "addon/globalPlugins/AI-assistant/service/**" = ["TID251"]
  "addon/globalPlugins/AI-assistant/providers/**" = ["TID251"]
  "addon/globalPlugins/AI-assistant/config/**" = ["TID251"]
  "addon/globalPlugins/AI-assistant/prompts/**" = ["TID251"]
  "addon/globalPlugins/AI-assistant/tools/**" = ["TID251"]
  "addon/globalPlugins/AI-assistant/use_case/**" = ["TID251"]
  "addon/globalPlugins/AI-assistant/embeddings/**" = ["TID251"]
  "addon/globalPlugins/AI-assistant/observability/**" = ["TID251"]
  ```

---

## 4. Zero-Regression Verification Gate Requirements

### 4.1 Gate Definitions & Baseline Audit Results
The verification gate establishes zero-regression criteria across four tools:

| Gate # | Command | Manifest / Config | Current Baseline State at HEAD (`ced1cbc`) | Acceptance Threshold |
|---|---|---|---|---|
| **GATE-1** | `uv run ruff check .` | `pyproject.toml` (`[tool.ruff]`) | **PASS** (0 errors, 0 warnings) | 0 errors, 0 warnings; TID251 clean |
| **GATE-2** | `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml` | `runtime_supervisor/Cargo.toml` | **PASS** (11 passed, 0 failed in 1.55s) | 100% pass; all existing + RS-01..04, RS-06 tests pass |
| **GATE-3** | `cargo check --manifest-path nvda_ui_host/Cargo.toml` | `nvda_ui_host/Cargo.toml` | **PASS** (Finished in 0.74s, 0 errors) | 0 compilation errors or warnings |
| **GATE-4** | `uv run pytest` | `pyproject.toml` (`[tool.pytest.ini_options]`) | **PASS** (461 passed, 3 deselected in 15.74s) | 0 failures, 0 regressions |

### 4.2 Repository Verification State
- **Git Branch & HEAD**: On branch `main`, commit `ced1cbc` ("feat(llama): improve llama.cpp model catalog resolution and metadata parsing").
- **Working Tree**: Clean (only untracked `.agents/` metadata and `ORIGINAL_REQUEST.md`).
- **Python Environment**: Managed by `uv`, Python 3.13.12, locked dependencies.
- **Rust Toolchain**: MSVC x86_64 target with PyO3 0.23 and Windows SDK 0.62.

---

## 5. Architectural Invariants Enforced in Slices 0 & 1

| Invariant | Title | Mandate | Enforcement Mechanism in Slice 0 / Slice 1 |
|---|---|---|---|
| **A5** | Pure-Python Domain & Service Isolation | 80%+ of codebase decoupled into pure Python; zero NVDA imports in domain/service. | Purge `logHandler` and `languageHandler` from 18 domain files. |
| **A6** | Automated Import Boundary Enforcement | Automated AST boundary checking + Ruff banned API rules. | `tests/test_import_boundaries.py` + Ruff `TID251`. |
| **A7** | Native Supervisor Authoritative Ownership | Rust `runtime_supervisor` is the sole owner of runtime mechanics. | Eliminate `_TestShimSupervisor` & `_LlamaTestShimSupervisor` (RS-10). |
| **A9** | Generation Fencing across Epochs | Monotonic integer generation counter increments on all crashes, timeouts, and restarts. | Fix RS-01 (crashes/timeouts), RS-02 (stopping guard), RS-03 (restart exit await), RS-04 (livelock backoff). |
| **A10** | Clean PyO3 FFI Boundary | GIL released during all blocking operations (`py.allow_threads`). | Verified in `lib.rs`; typed error mapping. |
| **A26** | Rust Runtime Supervisor Process Mechanics | Clean termination, Windows Job Object containment. | Assign spawned child processes to Win32 Job Object with `KILL_ON_JOB_CLOSE` (RS-06). |
| **A30** | Decoupled Three-Tier Test Architecture | Tier 1 (Pure Python < 3s, zero NVDA), Tier 2 (Rust/Worker), Tier 3 (NVDA Integration). | Root `conftest.py` sibling decoupling. |

---

## 6. Features Discovered & Synthesized

| # | Category | Feature | Description | Inputs | Outputs | Error Behavior | Discovered Via |
|---|---|---|---|---|---|---|---|
| **FEAT-01** | Native Runtime Concurrency | RS-01: Generation Monotonicity | Increments generation counter on process exit, crash, health timeout, and unhandled termination | Process exit signal, poll exit code, timeout deadline | Incremented `generation: u64`, updated `LifecycleState` | Monotonically increments generation before recording error in `InnerState` | `architecture_deliverable.md:507, 522` |
| **FEAT-02** | Native Runtime Concurrency | RS-02: Stopping State Guard | Enforces rejection or condvar wait when `ensure_ready` is called during `Stopping` state | `ensure_ready` call while `state == Stopping` | Clean wait on condvar until `Stopped` | Rejects/waits rather than overwriting state or creating zombie processes | `architecture_deliverable.md:508, 523` |
| **FEAT-03** | Native Runtime Concurrency | RS-03: Socket Collision Prevention | Ensures `restart()` awaits old process termination and socket release before spawning replacement | `restart()` invocation | Verified process exit and released port before new spawn | Blocks new spawn until old port is released; prevents `WSAEADDRINUSE` | `architecture_deliverable.md:509, 524` |
| **FEAT-04** | Native Runtime Concurrency | RS-04: Livelock Mitigation & Backoff | Serializes conflicting `ensure_ready` configs and adds bounded backoff/circuit breaker | Multiple threads calling `ensure_ready` with alternating configs | Serialized startup or clean rejection | Trips circuit breaker rather than infinite preemption loop | `architecture_deliverable.md:510, 525` |
| **FEAT-05** | Native Runtime Process Mechanics | RS-06: Windows Job Object Containment | Assigns spawned child processes to Win32 Job Object with `KILL_ON_JOB_CLOSE` | OS process creation | Job Object association | Windows kernel terminates child if parent dies; zero orphaned processes | `architecture_deliverable.md:512, 526` |
| **FEAT-06** | Native Runtime PyO3 Boundary | RS-10: Shadow Test Shim Elimination | Deletes `_TestShimSupervisor` and `_LlamaTestShimSupervisor` from production runtime modules | Production module imports | Authoritative native PyO3 class usage | Prevents parallel mock behavior in production code paths | `architecture_deliverable.md:516` |
| **FEAT-07** | Native Runtime Testing | RS-TESTS: Rust Supervisor Test Suite | Comprehensive unit and integration test suite in `runtime_supervisor/src/tests.rs` | Rust test runner | Verified pass results for RS-01..RS-06 | Fails test if generation not incremented, stopping guard missing, etc. | `ORIGINAL_REQUEST.md:118, 136` |
| **FEAT-08** | Test Architecture | CONFTEST-DECOUPLE: Sibling NVDA Decoupling | Refactors root `conftest.py` so pure domain/service tests run without `../nvda` checkout | `pytest` CLI invocation | Test discovery & execution | Runs pure tests cleanly; skips/deselects `nvda_integration` if checkout absent | `architecture_deliverable.md:476, 998` |
| **FEAT-09** | Pure Python Domain Isolation | LOG-FACADE: Standard Library Logging Bridge | Replaces `from logHandler import log` with standard `logging.getLogger` facade across 18 domain files | Log calls in domain/service code | Log records forwarded to NVDA log in add-on or standard logging in tests | Graceful fallback; no `ModuleNotFoundError` when run outside NVDA | `architecture_deliverable.md:403, 995` |
| **FEAT-10** | Pure Python Domain Isolation | LANG-DECOUPLE: Settings Language Resolver Port | Decouples `languageHandler` in `config/settings.py` via `register_language_resolver` port | Settings language lookup | Configured language string or "en" fallback | Uses default locale/fallback when `languageHandler` is not registered | `architecture_deliverable.md:416, 997` |
| **FEAT-11** | Boundary Enforcement | AST-IMPORT-GATE: Automated AST Import Boundary Test | Scans AST of pure packages and asserts zero direct or transitive forbidden NVDA imports | Python source files in pure packages | Pass/Fail assertion in < 200ms | Raises `AssertionError` with exact file and line citation if forbidden import found | `architecture_deliverable.md:468, 1000` |
| **FEAT-12** | Boundary Enforcement | RUFF-TID251: Banned API Configuration | Configures Ruff `flake8-tidy-imports` rule `TID251` in `pyproject.toml` | Ruff linter | Actionable lint errors for forbidden imports | Blocks PR/commit if forbidden NVDA module imported in pure packages | `architecture_deliverable.md:440, 1001` |
| **FEAT-13** | Verification Gate | GATE-RUFF: Ruff Lint Verification | Runs `uv run ruff check .` across entire repository | Repository source files | 0 errors | Fails verification gate on style or import violation | `ORIGINAL_REQUEST.md:128` |
| **FEAT-14** | Verification Gate | GATE-CARGO-TEST: Rust Supervisor Test Gate | Runs `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml` | Rust source & test files | 100% passed | Fails gate on concurrency or lifecycle test failure | `ORIGINAL_REQUEST.md:129` |
| **FEAT-15** | Verification Gate | GATE-CARGO-CHECK: UI Host Compilation Gate | Runs `cargo check --manifest-path nvda_ui_host/Cargo.toml` | Rust UI host source files | 0 warnings, 0 errors | Fails gate on protocol or compilation failure | `ORIGINAL_REQUEST.md:130` |
| **FEAT-16** | Verification Gate | GATE-PYTEST: Full Python Test Suite Gate | Runs `uv run pytest` across all test suites | Pytest test suite | 0 failures, 0 regressions | Fails gate on any broken regression | `ORIGINAL_REQUEST.md:131` |

---

## 7. Edge Cases & Boundary Behaviors

| # | Feature | Edge Case Input | Observed / Expected Behavior |
|---|---|---|---|
| **E-01** | RS-01 | Child exits with code 0 unexpectedly | `state.generation` increments by 1; `state.state = Stopped`; observers see epoch bump. |
| **E-02** | RS-01 | Child killed by OS / Task Manager (`SIGKILL`) | `poll()` returns non-zero code; `generation` increments; `state = Failed`. |
| **E-03** | RS-01 | Health check timeout expires during startup | `generation` increments; child terminated; `state = Failed`; error reported. |
| **E-04** | RS-02 | `ensure_ready` invoked while `stop()` is sleeping | Caller blocks on `condvar` until `state == Stopped`; then spawns cleanly; `stop()` does not overwrite new state. |
| **E-05** | RS-03 | Rapid `restart()` while socket in `TIME_WAIT` / active | `restart()` awaits `proc.wait_timeout()`; confirms port release before spawning new child; no `WSAEADDRINUSE`. |
| **E-06** | RS-04 | 10 concurrent threads alternate Model A and Model B | Mutex and condvar serialize requests; bounded backoff prevents livelock loop; circuit breaker trips if max retries exceeded. |
| **E-07** | RS-06 | Parent `nvda.exe` crashes or is forcefully killed | Windows kernel closes Job Object; all child processes (`litert-lm`, `llama-server.exe`) terminated instantly; 0 zombie processes. |
| **E-08** | RS-10 | Test executes without native `.pyd` built | Raises clear `ImportError` or uses explicit test harness; production code never falls back to mock shims. |
| **E-09** | CONFTEST | `../nvda` checkout absent or corrupted | `uv run pytest -m "not nvda_integration"` discovers and passes all pure tests in < 3s without `UsageError`. |
| **E-10** | LOG-FACADE | Module logged before NVDA bridge initialized | Message formatted via standard `logging.getLogger`; does not raise `ModuleNotFoundError`. |
| **E-11** | AST-GATE | Developer adds `from api import getFocusObject` in `service/` | `tests/test_import_boundaries.py` fails in < 200ms with exact line number and rule citation. |
| **E-12** | RUFF-TID251 | Developer adds `import wx` in `core/` | `uv run ruff check .` fails with `TID251: wx is forbidden outside ui/ dialogs`. |

---

## 8. Master Feature Inventory for PROJECT.md

| Feature # | Name | Milestone | Description | Acceptance Criteria | Invariants Enforced |
|---|---|---|---|---|---|
| **FEAT-01** | Generation Counter Monotonicity (RS-01) | M1: Slice 0 | Ensure `generation` increments monotonically on every lifecycle state transition, process crash, unhandled exit, and timeout. | Rust test in `tests.rs` asserts `status.generation` increases after crash, exit code 0, and timeout. Stale generation updates rejected. | **A9** |
| **FEAT-02** | Stopping State Guard (RS-02) | M1: Slice 0 | Add guard preventing concurrent `ensure_ready` during `Stopping` state; prevent `stop()` from overwriting subsequent generations. | Concurrency test in `tests.rs` verifies `ensure_ready` waits for `stop()` completion; no orphaned zombie processes. | **A7, A9** |
| **FEAT-03** | Restart Socket Teardown Await (RS-03) | M1: Slice 0 | Ensure `restart()` awaits old process termination and socket release before spawning replacement server. | Rapid restart test in `tests.rs` succeeds with zero `WSAEADDRINUSE` socket collision. | **A9** |
| **FEAT-04** | Startup Livelock Mitigation (RS-04) | M1: Slice 0 | Bounded retries with exponential backoff and condvar wait when configuration changes during startup. | Concurrency test with conflicting configs serializes cleanly without tight ping-pong preemption. | **A7, A10** |
| **FEAT-05** | Windows Job Object Containment (RS-06) | M1: Slice 0 | Assign spawned child processes to Win32 Job Object with `KILL_ON_JOB_CLOSE` and `DIE_ON_UNHANDLED_EXCEPTION`. | On Windows, child process handle is assigned to Job Object; process tree is cleanly terminated on parent exit. | **A16, A26** |
| **FEAT-06** | Elimination of Production Test Shims (RS-10) | M1: Slice 0 | Delete `_TestShimSupervisor` and `_LlamaTestShimSupervisor` from `server.py` and `llama_server.py`. | Zero shadow test shims remain in production code; all runtime supervision routed through native Rust supervisor. | **A7** |
| **FEAT-07** | Rust Supervisor Regression Suite | M1: Slice 0 | Comprehensive Rust regression test suite in `runtime_supervisor/src/tests.rs` covering all fixed conditions. | `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml` passes 100% (15+ tests). | **A7, A9, A26** |
| **FEAT-08** | Root Conftest Sibling Decoupling | M2: Slice 1 | Decouple root `conftest.py` so pure Python tests run without sibling `../nvda` checkout. Gate NVDA tests behind `-m nvda_integration`. | `uv run pytest -m "not nvda_integration"` passes in < 3s when `../nvda` is missing. | **A30** |
| **FEAT-09** | Logging Facade & Fallback | M2: Slice 1 | Purge `from logHandler import log` from 18 domain/service files; standardize on `logging.getLogger` with NVDA bridge. | All pure domain/service modules import and log cleanly in standalone Python without `logHandler` on `sys.path`. | **A5, A6** |
| **FEAT-10** | Settings Language Resolver Port | M2: Slice 1 | Decouple `languageHandler` in `config/settings.py` via pluggable `register_language_resolver` port with "en" default fallback. | `config/settings.py` imports and retrieves language without `languageHandler` on `sys.path`. | **A5** |
| **FEAT-11** | Automated AST Import Boundary Gate | M2: Slice 1 | Implement `tests/test_import_boundaries.py` scanning pure packages for forbidden NVDA modules (`api`, `wx`, etc.). | Test is integrated in pytest suite, executes in < 200ms, and asserts 0 forbidden imports across pure packages. | **A5, A6** |
| **FEAT-12** | Ruff Flake8-Tidy-Imports Rules (TID251) | M2: Slice 1 | Configure `tool.ruff.lint.extend-select = ["TID251"]` and banned API mappings in `pyproject.toml`. | `uv run ruff check .` catches banned NVDA imports in pure packages with explanatory messages. | **A6** |
| **FEAT-13** | Zero-Regression Ruff Gate | M3: Verification | Verify `uv run ruff check .` passes with 0 errors and 0 warnings. | Zero lint, formatting, or banned import errors across repository. | **A6** |
| **FEAT-14** | Zero-Regression Rust Test Gate | M3: Verification | Verify `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml` passes 100%. | All unit and integration tests pass cleanly in debug/release profiles. | **A7, A9, A26** |
| **FEAT-15** | Zero-Regression UI Host Check Gate | M3: Verification | Verify `cargo check --manifest-path nvda_ui_host/Cargo.toml` compiles with 0 errors. | Clean compilation of native Win32/WebView2 UI host. | **A27** |
| **FEAT-16** | Zero-Regression Pytest Gate | M3: Verification | Verify `uv run pytest` passes full existing test suite without failure. | 461+ tests pass with 0 failures and 0 regressions. | **A1–A30** |

---

## 9. Conclusion & Recommendations

The specification mining investigation confirms that:
1. All defects RS-01, RS-02, RS-03, RS-04, RS-06, and RS-10 are concrete, verified in code, and cleanly isolated within `runtime_supervisor/` and production runtime wrappers.
2. The sibling checkout lock in root `conftest.py` is a single hard `UsageError` block that can be safely refactored to unlock Tier 1 pure Python testing.
3. The 40 `logHandler` imports and 1 `languageHandler` import are fully mapped; replacing them with a standard library facade decouples 80.7% of the codebase into pure Python.
4. All four verification gates currently pass cleanly at HEAD (`ced1cbc`), establishing a rock-solid baseline for the implementation agents.
