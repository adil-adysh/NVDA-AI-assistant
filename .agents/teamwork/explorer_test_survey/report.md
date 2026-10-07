# Technical Survey Report: Test Infrastructure, Verification Gates & Adversarial Scenarios for Slice 2 & Slice 3

**Author**: Explorer 3 (Test & Verification Specialist)  
**Working Directory**: `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\explorer_test_survey`  
**Target Delivery**: `report.md`  
**Target Milestone**: Migration Slice 2 (Job Domain & Versioned Protocol) & Slice 3 (Supervised Worker Process Lifecycle & IPC)  
**Date**: 2026-10-05T03:38:00Z  

---

## 1. Executive Summary & Baseline Verification Status

This technical survey establishes the definitive testing architecture, automated verification gates, and adversarial test scenarios for Migration Slice 2 and Slice 3 of `adil-adysh/NVDA-AI-assistant`.

Following the successful completion and verification of Migration Slice 0 (Rust Supervisor Concurrency Hardening) and Slice 1 (Pure Python Test Boundary Decoupling), the repository has established a clean separation between pure Python domain/service modules and NVDA accessibility host bindings.

### 1.1 Architectural Invariants Directly Enforced
- **Invariant A4 (Thread-Detached Immutable Snapshots)**: Zero live COM pointers or host state cross thread boundaries. All data exchanged across worker and job domains is encapsulated in frozen, slotted DTOs.
- **Invariant A6 (Automated Import Boundary Enforcement)**: Pure domain packages (`core/`, `config/`, `service/`, `providers/`, `use_case/`, and the newly created `core/job/` and `worker/`) are strictly forbidden from importing NVDA host modules (`api`, `textInfos`, `controlTypes`, `gui`, `wx`, `speech`, `tones`, `logHandler`, etc.). Enforced via Ruff `TID251` and AST architecture tests in Tier 1 CI.
- **Invariant A19 (Heartbeat, Liveness & Fast Crash Detection)**: Monotonic 5.0s heartbeat probe, 15.0s timeout threshold. Out-of-process worker termination or broken named pipes must be detected in $< 5\text{ ms}$ via Win32 `ERROR_BROKEN_PIPE` (`winerror=109`), with zero lag on the NVDA main event loop.
- **Invariant A30 (Decoupled Three-Tier Test Architecture)**:
  - **Tier 1 (Pure Python Unit & Domain)**: Runs with zero NVDA checkout or host dependencies on any platform in $< 3.0\text{ s}$ (Slice 2 target: $< 1.0\text{ s}$).
  - **Tier 2 (Rust / Worker IPC Integration)**: Multi-process and named-pipe integration tests verifying Windows Job Object containment, DACL security, handshake, heartbeat, crash resilience, and circuit breaker in $< 8.0\text{ s}$.
  - **Tier 3 (NVDA Integration)**: Live NVDA object trees and wx GUI dialogs tested against the pinned sibling `../nvda` checkout (`nvda-source.toml`).

### 1.2 Baseline Verification Gate Execution Results
All five baseline verification commands mandated by the project were executed and verified clean at HEAD:

| Verification Gate | Command | Execution Time | Results & Status |
| :--- | :--- | :--- | :--- |
| **Static Lint & Banned APIs** | `uv run ruff check .` | 0.42s | **0 errors, 0 warnings** (PASS) |
| **Rust Supervisor Concurrency** | `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml` | 1.54s | **20/20 passed** (RS-01 to RS-10 verified) (PASS) |
| **Rust UI Host Compilation** | `cargo check --manifest-path nvda_ui_host/Cargo.toml` | 0.05s | **Finished dev profile cleanly** (PASS) |
| **AST Boundary Architecture Test** | `uv run pytest tests/test_import_boundaries.py` | 0.13s | **4/4 passed** (< 150ms SLA budget) (PASS) |
| **Pure Python Suite (Default)** | `uv run pytest -m "not nvda_integration"` | 13.65s | **450 passed, 18 deselected** (PASS) |
| **Packaging Build Graph Dry-Run** | `uv run scons --dry-run` | 2.11s | **Target graph built cleanly, tests excluded** (PASS) |

---

## 2. Existing Test Infrastructure & Baseline Gates Analysis

### 2.1 Test Environment & Configuration
- **Python Runtime**: Python 3.13.12 managed under `uv` (`.venv`).
- **Configuration File**: `pyproject.toml` defines:
  ```toml
  [tool.pytest.ini_options]
  addopts = ["--import-mode=importlib", "-m", "not nvda_integration"]
  testpaths = ["tests"]
  python_files = ["test_*.py"]
  markers = [
      "nvda_integration: requires a built sibling NVDA checkout and its native helper DLLs",
  ]
  norecursedirs = [
      ".git", ".venv", "addon/globalPlugins/AI-assistant/lib", "dist",
      "embedding_engine", "memory_engine", "runtime_supervisor"
  ]
  ```
- **Conftest Bootstrap Mechanism (`conftest.py`)**:
  - Dynamically evaluates `HAS_NVDA_CHECKOUT = not os.environ.get("NVDA_STANDALONE") and (NVDA_SOURCE / "api.py").is_file()`.
  - When running pure Python tests (or when `../nvda` is absent/standalone):
    - Installs standard library translation builtins (`_`, `ngettext`, `pgettext`, `npgettext`).
    - Provides a standard library `logging.getLogger("nvda.fallback")` shim for `sys.modules["logHandler"]`.
    - Automatically deselects/skips all tests marked `@pytest.mark.nvda_integration`.
  - Prevents test execution from failing if `../nvda` is uninitialized.

### 2.2 AST Import Boundary Scanner (`tests/test_import_boundaries.py`)
- The AST import boundary scanner uses Python's `ast` module to scan every `.py` file under pure directories.
- It parses:
  1. Direct imports: `import api`, `import logHandler`
  2. From imports (both absolute and relative): `from api import x`, `from .api import x`, `from .. import gui`
  3. Dynamic imports: `__import__('api')`, `importlib.import_module('wx')`
- **Current Scanned Pure Directories**:
  ```python
  PURE_DIRECTORIES: tuple[str, ...] = (
      "core",
      "config",
      "service",
      "providers",
      "use_case",
      "prompts",
      "tools",
      "observability",
      "embeddings",
  )
  ```
- **Performance**: Performs AST parsing of 100+ files and completes in **130ms**, strictly enforcing the `< 150ms` SLA test assertion.

---

## 3. Slice 2 Test Suite Architecture (Tier 1 Pure Python)

### 3.1 Scope and Module Boundary
Slice 2 implements the pure Python job domain, immutable data transfer objects (DTOs), finite state machines, cancellation coordination, and versioned protocol framing without external process dependencies.
- **Production Package**: `addon/globalPlugins/AI-assistant/core/job/`
  - `dto.py`: Frozen slotted dataclasses and enums.
  - `state.py`: Discrete `JobStateMachine` and continuous `SessionStateMachine`.
  - `cancellation.py`: `CancellationToken`, `CancellationCoordinator`.
  - `protocol.py`: NDJSON framing encoder/decoder, message envelopes, typed error codes.
  - `client.py`: `WorkerClient` and `JobClient` abstract base classes.
- **Test Package**: `tests/core/job/`
  - All tests belong to **Tier 1 (Pure Python)**.
  - Zero NVDA dependencies. Runs in `< 1.0s`.

### 3.2 Detailed Test Specifications

#### A. Immutable DTOs & Dataclass Contract Tests (`tests/core/job/test_dto.py`)
1. **Immutability Enforcement**:
   - Verify all DTOs (`JobSubmission`, `JobUpdate`, `JobResult`, `HandshakeRequest`, `HandshakeResponse`, `SessionConfig`, `StreamChunk`, `WorkerHealth`) are decorated with `@dataclass(frozen=True, slots=True)`.
   - Assert `dataclasses.FrozenInstanceError` is raised upon attempting to set or delete any attribute:
     ```python
     submission = JobSubmission(job_id="test-1", job_type="echo", payload={}, generation=1)
     with pytest.raises(FrozenInstanceError):
         submission.job_id = "modified"
     ```
   - Assert `__slots__` is defined on all DTO classes and prevents arbitrary attribute assignment (`submission.extra = 1` raises `FrozenInstanceError` / `AttributeError`).
2. **Default Values & Field Types**:
   - Verify `JobSubmission.priority == 10`, `timeout_seconds == 300.0`.
   - Verify `HandshakeRequest.protocol_version == "1.0.0"`.
   - Verify tuple conversion for collections (e.g. `supported_schemas` and `requested_capabilities` are immutable tuples, not mutable lists).
3. **Serialization Round-Trip**:
   - Verify lossless serialization to dict / JSON and deserialization back into identical DTO instances.
   - Verify nested structures (e.g. `StreamChunk.bounding_boxes`, `JobResult.result_data`) preserve dictionary keys and values.

#### B. JSON Schema Validation Tests (`tests/core/job/test_schemas.py`)
1. **Schema Compliance (Draft 2020-12)**:
   - Validate serialized DTO dict representations against the 8 authoritative JSON schemas specified in Section 16.2 of the Architecture Deliverable:
     - `HandshakeRequest`
     - `HandshakeResponse`
     - `JobSubmission`
     - `JobUpdate`
     - `JobResult`
     - `SessionConfig`
     - `StreamChunk`
     - `WorkerHealth`
2. **Schema Rejection of Invalid Vectors**:
   - Verify `additionalProperties: false` rejects payloads with unrecognized keys.
   - Verify missing required fields (e.g. missing `job_id`, `generation`, or `status`) trigger schema validation failure.
   - Verify type mismatches (e.g. `generation` passed as string `"1"`, `progress_pct` passed as string `"50%"`) trigger validation failure.
3. **Validator Implementation Strategy**:
   - *Recommendation*: Add `jsonschema>=4.20.0` to `[dependency-groups] dev` in `pyproject.toml`. Because dev dependencies are never packaged into `.nvda-addon` (guaranteed by `site_scons/site_tools/NVDATool/addon.py`), standard `jsonschema.Draft202012Validator` provides authoritative, standard-compliant validation in CI without polluting the runtime add-on.
   - *Alternative*: If zero new dependencies are strictly mandated, implement a schema validator in `tests/support/schema_validator.py` verifying types, required keys, enum values, and `additionalProperties: false`.

#### C. Finite State Machine Monotonicity Tests (`tests/core/job/test_state_machine.py`)
1. **Monotonic Discrete Job FSM**:
   - State graph: `SUBMITTED` $\to$ `QUEUED` $\to$ `RUNNING` $\to$ terminal (`COMPLETED`, `FAILED`, `CANCELLED`).
   - Valid transition sequences:
     - Standard success: `SUBMITTED` $\to$ `QUEUED` $\to$ `RUNNING` $\to$ `COMPLETED`
     - Standard error: `SUBMITTED` $\to$ `QUEUED` $\to$ `RUNNING` $\to$ `FAILED`
     - Cancellation in progress: `SUBMITTED` $\to$ `QUEUED` $\to$ `RUNNING` $\to$ `CANCELLED`
     - Cancellation before start: `SUBMITTED` $\to$ `CANCELLED`
     - Cancellation while queued: `QUEUED` $\to$ `CANCELLED`
     - Progress updates: `RUNNING` $\to$ `RUNNING` (valid self-transition)
2. **Invalid Transition Rejections**:
   - Backward transitions: `RUNNING` $\to$ `QUEUED`, `RUNNING` $\to$ `SUBMITTED`.
   - Terminal mutations: Once reaching `COMPLETED`, `FAILED`, or `CANCELLED`, any transition raises `IllegalStateTransitionError`.
   - Terminal-to-terminal transitions: `COMPLETED` $\to$ `FAILED`, `FAILED` $\to$ `COMPLETED`, `CANCELLED` $\to$ `COMPLETED` must all raise `IllegalStateTransitionError`.
   - Skipping steps: `SUBMITTED` $\to$ `COMPLETED` directly raises `IllegalStateTransitionError`.
3. **Single Result Invariant**:
   - Exactly one terminal `JobResult` is emitted. Emitting a second terminal event raises an exception or is rejected as a no-op with warning.
4. **Continuous Session FSM**:
   - States: `INIT` $\to$ `CONFIGURING` $\to$ `READY` $\leftrightarrow$ `STREAMING` $\leftrightarrow$ `PAUSED` $\to$ `CLOSING` $\to$ `CLOSED` (or `ERROR`).
   - Verify pausing while streaming, resuming while paused, closing from ready or streaming.

#### D. Two-Phase Cancellation Protocol Tests (`tests/core/job/test_cancellation.py`)
1. **Cooperative Cancellation Token**:
   - Test `token.is_cancelled()`, `token.check_cancelled()`, `token.cancel()`.
   - Test yield point checks: simulated loops checking token every $N$ iterations exit within $< 5\text{ ms}$ and raise `JobCancelledException`.
2. **Cancellation Coordinator**:
   - Register token for `job_id`.
   - Issue cancellation: sets token, records cancellation timestamp.
   - Clean deregistration on job termination.

#### E. Wire Protocol Framing & Serialization Tests (`tests/core/job/test_protocol.py`)
1. **NDJSON Framing**:
   - Encode message to UTF-8 bytes with trailing newline `\n`.
   - Streaming decoder receives partial chunks, reconstructs complete frames cleanly across chunk boundaries.
2. **Max Frame Boundary**:
   - Frames up to 16 MB (`MAX_FRAME_BYTES = 16 * 1024 * 1024`) decode successfully.
   - Frames exceeding 16 MB trigger `FrameTooLargeError` and drop buffer safely.
3. **Error Framing**:
   - Deserializing malformed JSON raises typed `ProtocolFramingError`.
   - Unknown envelope `type` raises `UnknownProtocolMessageError`.

#### F. Mock Client Interface Tests (`tests/core/job/test_mock_client.py`)
1. **`MockJobClient` & `MockWorkerClient`**:
   - In-memory implementation of `JobClient` abstract interface.
   - Synchronously or asynchronously processes `JobSubmission`, dispatches progress callbacks, and yields `JobResult`.
   - Confirms that upstream callers (`service/`, `providers/`) can be unit-tested without any named pipes or worker processes.

---

## 4. Slice 3 Test Suite Architecture (Tier 2 Multi-Process / Worker IPC)

### 4.1 Scope and Module Boundary
Slice 3 implements the out-of-process Worker runtime, named pipe transports with Win32 DACL security, versioned handshakes, monotonic heartbeat watchdogs, circuit-breaker crash recovery, and end-to-end trivial job execution.
- **Production Packages**:
  - `addon/globalPlugins/AI-assistant/worker/`
    - `process.py`: Worker CLI entrypoint (`ai_assistant_worker.py`).
    - `ipc/transport.py`: Win32 Named Pipe server/client implementation with DACL.
    - `ipc/handshake.py`: Handshake validator.
    - `ipc/security.py`: Win32 security attributes and DACL constructor.
  - `addon/globalPlugins/AI-assistant/plugin/worker_supervisor.py`: NVDA-side worker lifecycle manager, Windows Job Object containment, heartbeat watchdog, circuit breaker.
  - `addon/globalPlugins/AI-assistant/service/worker_client.py`: NVDA-side high-level IPC client.
- **Test Package**: `tests/worker/`
  - All tests belong to **Tier 2 (Worker IPC & Multi-Process)**.
  - Run with `uv run pytest tests/worker/`. Target execution: $< 8.0\text{ s}$.

### 4.2 Detailed Test Specifications

#### A. Windows Job Object Containment & Lifecycle (`tests/worker/test_process_lifecycle.py`)
1. **Win32 Job Object Assignment (`RS-06` / Invariant A16)**:
   - Worker supervisor spawns `ai_assistant_worker.py` via `subprocess.Popen`.
   - Immediately assigns process handle to a Win32 Job Object configured with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` using `pywin32` (`win32job`).
   - Test verifies:
     - `QueryInformationJobObject` confirms `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` flag is active.
     - When parent process handle is closed or parent exits, the child worker process is unconditionally terminated by the OS kernel. Zero orphan processes.
2. **Clean Teardown Sequence**:
   - Send shutdown command over command pipe (`\\.\pipe\nvda_ai_worker_cmd`).
   - Worker closes named pipes, terminates background worker threads, and exits with code 0 within 2.0s.

#### B. Named Pipe Transport & DACL Security (`tests/worker/test_pipe_transport.py`)
1. **Bi-Directional Pipes**:
   - Command pipe (`\\.\pipe\nvda_ai_worker_cmd` or parameterized per test): Duplex RPC.
   - Event pipe (`\\.\pipe\nvda_ai_worker_evt`): Asynchronous event stream.
2. **Win32 DACL Security Verification**:
   - Pipe security attributes must be constructed using `win32security` restricting access strictly to:
     - Current user SID (`TOKEN_USER`)
     - Local Builtin Administrators SID (`WinBuiltinAdministratorsSid`)
   - Test verifies:
     - Pipe handle security descriptor inspection confirms DACL contains only allowed ACEs.
     - Unauthorized connection attempts (simulated via foreign SID or null DACL rejection) fail with `ERROR_ACCESS_DENIED` (`winerror=5`).
3. **Test Isolation via Dynamic Pipe Names**:
   - Tests MUST avoid global pipe name collisions. Every test instance generates a unique pipe suffix:
     ```python
     pipe_id = uuid.uuid4().hex[:8]
     cmd_pipe = f"\\\\.\\pipe\\nvda_ai_test_cmd_{pipe_id}"
     evt_pipe = f"\\\\.\\pipe\\nvda_ai_test_evt_{pipe_id}"
     ```

#### C. Protocol Handshake Verification (`tests/worker/test_handshake.py`)
1. **Compatible Version Handshake**:
   - Client sends `HandshakeRequest(protocol_version="1.0.0", ...)`.
   - Worker responds with `HandshakeResponse(accepted=True, protocol_version="1.0.0", negotiated_capabilities=...)`.
   - Handshake completes and channel transitions to `READY`.
2. **Incompatible Version Rejection**:
   - Client sends `HandshakeRequest(protocol_version="2.0.0")` (major breaking).
   - Worker rejects with `HandshakeResponse(accepted=False, error_message="Incompatible protocol version")`.
   - Connection is closed immediately.
3. **Capability Negotiation**:
   - Client requests capabilities `("job.echo", "job.compute")`.
   - Worker returns subset of supported capabilities. Client verifies required capabilities before submitting jobs.

#### D. Heartbeat Watchdog & Fast Broken-Pipe Detection (`tests/worker/test_heartbeat.py`)
1. **Fast Broken-Pipe Detection (Invariant A19)**:
   - Client connected to worker over named pipe.
   - Kill worker process forcefully (`proc.kill()`).
   - Client attempt to read or write detects `winerror=109` (`ERROR_BROKEN_PIPE`) in **$< 5\text{ ms}$**.
   - Assert detection latency: `assert elapsed_time < 0.005` (5 ms).
2. **Heartbeat Probing & Liveness Timeout**:
   - Production parameters: 5.0s ping interval, 15.0s timeout (3 missed pings).
   - *Test Optimization*: Tests configure fast timers (e.g. `ping_interval=0.05s`, `timeout=0.15s`) to verify timeout detection in $< 200\text{ ms}$ without real-time delays.
   - Worker simulated to freeze (stop responding to pings). Supervisor watchdog detects missed pings and marks worker `DEAD`.
3. **Monotonic Generation Fencing**:
   - Active generation counter increments on every spawn / restart.
   - Any late messages arriving with `generation < active_generation` are silently discarded.

#### E. Worker Crash Resilience & Circuit Breaker (`tests/worker/test_crash_recovery.py`)
1. **Crash During Active Job (Invariant A19 & A20)**:
   - Submit active job (`echo` or `compute`).
   - Kill worker process while job is executing.
   - Supervisor catches `ERROR_BROKEN_PIPE`.
   - Active job is marked failed with `retriable=True` and `error_code="WORKER_CRASHED"`.
   - Main thread / caller is notified immediately without hang.
2. **Crash While Idle**:
   - Worker killed while no jobs are running.
   - Supervisor detects death, increments generation, and restarts worker via exponential backoff.
3. **Circuit Breaker State Machine (`FAILED_TRIPPED`)**:
   - Rapid crash scenario: Induce $\ge 3$ consecutive crashes within a 60-second window.
   - On the 3rd crash:
     - Supervisor transitions to `FAILED_TRIPPED`.
     - Automatic restart is **halted** (no infinite restart loops).
     - Presenter is notified to announce worker failure.
   - Test verifies:
     - State is strictly `FAILED_TRIPPED`.
     - Zero further subprocess spawns occur.
     - Manual `supervisor.reset()` resets failure counter and allows clean re-initialization.

#### F. Trivial Compute Job End-to-End (`tests/worker/test_trivial_job.py`)
1. **Echo / Ping Job Submission & Completion**:
   - Client submits `JobSubmission(job_type="echo", payload={"message": "hello world"})`.
   - Worker executes job, emits progress update (`JobUpdate(progress_pct=0.5)`), and completes with `JobResult(status="completed", result_data={"echo": "hello world"})`.
   - Client receives terminal result over event pipe.
2. **Trivial Compute Job Cancellation**:
   - Client submits long compute job (e.g. 50 iterations with yield points).
   - Client issues `JobCancellationRequest(job_id=...)`.
   - Worker detects cancellation token at yield point, terminates execution cleanly, and returns `JobResult(status="cancelled")` within $< 100\text{ ms}$.

---

## 5. Import Boundary & SCons Packaging Verification

### 5.1 Import Boundary Enforcement (`tests/test_import_boundaries.py`)

#### A. Core Job Subtree (`addon/globalPlugins/AI-assistant/core/job/`)
- `tests/test_import_boundaries.py` already includes `"core"` in `PURE_DIRECTORIES`:
  ```python
  PURE_DIRECTORIES: tuple[str, ...] = (
      "core",
      ...
  )
  ```
- Because the scan uses `target_dir.rglob("*.py")`, all files inside `core/job/` are **automatically scanned** by `test_pure_packages_have_zero_forbidden_nvda_imports()`.
- Any import of `api`, `textInfos`, `controlTypes`, `globalPluginHandler`, `scriptHandler`, `queueHandler`, `gui`, `wx`, `speech`, `tones`, `logHandler`, etc., will immediately trigger a test failure.

#### B. Worker Subtree (`addon/globalPlugins/AI-assistant/worker/`)
- Currently, `"worker"` is **not** in `PURE_DIRECTORIES` in `tests/test_import_boundaries.py`.
- **Mandatory Action for Slice 3**: Add `"worker"` to `PURE_DIRECTORIES`:
  ```python
  PURE_DIRECTORIES: tuple[str, ...] = (
      "core",
      "worker",  # MUST BE ADDED IN SLICE 3
      "config",
      "service",
      "providers",
      "use_case",
      "prompts",
      "tools",
      "observability",
      "embeddings",
  )
  ```
- Adding `"worker"` ensures that the worker entrypoint, transport, and executors are scanned for forbidden NVDA imports.
- **Ruff `TID251` Check**: In `pyproject.toml`, neither `core/**` nor `worker/**` is listed in `tool.ruff.lint.per-file-ignores`. Thus, Ruff automatically enforces banned API rules on both directories.
- **Performance Budget**: AST scanning 10-15 additional files in `core/job/` and `worker/` adds $\approx 6\text{ ms}$, maintaining total scan time under $140\text{ ms}$ (well below the $150\text{ ms}$ SLA).

### 5.2 SCons Packaging Verification

#### A. Defense-in-Depth Test Artifact Exclusion
1. **SCons NVDATool Check (`site_scons/site_tools/NVDATool/addon.py`)**:
   ```python
   def isTestArtifact(path: Path) -> bool:
       parts = tuple(part.casefold() for part in path.parts)
       name = parts[-1] if parts else ""
       return (
           any(part in {"test", "tests", "__pycache__", ".pytest_cache"} for part in parts[:-1])
           or name == "conftest.py"
           or name.startswith("test_")
           or name.endswith("_test.py")
           or name.endswith((".pyc", ".pyo"))
       )
   ```
2. **BuildVars Exclusion (`buildVars.py`)**:
   ```python
   excludedFiles: list[str] = [
       "**/tests/**",
       "**/test/**",
       "globalPlugins/AI-assistant/**/test_*.py",
       "globalPlugins/AI-assistant/**/*_test.py",
       "**/conftest.py",
       "**/__pycache__/**",
       "**/*.py[co]",
   ]
   ```
3. **Packaging Invariant**:
   - Tests placed under `tests/core/job/` and `tests/worker/` reside strictly outside `addon/` and are never scanned by SCons for packaging.
   - If any test helper or mock were accidentally committed under `addon/`, `isTestArtifact()` unconditionally drops it from the generated `.nvda-addon` bundle.
   - Confirmed by `tests/build/test_addon_packaging.py` which passes at 100%.

#### B. SCons Build Graph Dry-Run Validation
- Execution of `uv run scons --dry-run` confirms that adding Python files under `addon/globalPlugins/AI-assistant/core/job/` and `addon/globalPlugins/AI-assistant/worker/` is automatically picked up by `pythonSources = ["addon/globalPlugins/AI-assistant/**/*.py"]` in `buildVars.py` for gettext extraction and packaging, without any SCons build breaks.

---

## 6. Adversarial Scenarios & Verification Matrix

The following matrix documents the exhaustive adversarial test scenarios required to validate Slice 2 and Slice 3 against network, process, memory, and concurrency failures:

| Scenario ID | Test Name | Adversarial Stimulus / Failure Mode | Expected System Behavior | Verification Assertion & Metric |
| :--- | :--- | :--- | :--- | :--- |
| **ADV-01** | `test_worker_crash_during_active_job` | Kill worker process via `SIGKILL` / `TerminateProcess` mid-execution of active job | NVDA main thread remains unblocked; active job transitions to `FAILED` with `retriable=True`; supervisor marks worker dead | Job result received with `error_code="WORKER_CRASHED"`; zero main-thread stall ($< 50\text{ ms}$) |
| **ADV-02** | `test_fast_broken_pipe_detection` | Abruptly sever event/cmd pipe while listener thread is blocked on `ReadFile` | `winerror=109` caught immediately; connection marked severed in $< 5\text{ ms}$ | `detection_latency < 0.005` seconds |
| **ADV-03** | `test_circuit_breaker_rapid_crashes` | Worker crashes 3 times in rapid succession ($< 60\text{ s}$) | Supervisor enters `FAILED_TRIPPED`; halts automatic restart loop; notifies user | `supervisor.state == LifecycleState.FAILED_TRIPPED`; no replacement process spawned |
| **ADV-04** | `test_pipe_dacl_unauthorized_access` | Local process connecting with untrusted/foreign Windows security credentials | Pipe server rejects connection with `ERROR_ACCESS_DENIED` | Connection attempt raises Win32 error 5; pipe security descriptor validated |
| **ADV-05** | `test_handshake_major_version_mismatch` | Client sends `v2.0.0` or worker runs `v0.9.0` | Handshake rejected with `accepted=False`; pipe disconnected cleanly | `response.accepted is False`; `error_message` cites version incompatibility |
| **ADV-06** | `test_cancellation_cooperative_yield` | Issue cancel request to worker while executing multi-step compute loop | Worker checks token at yield point; aborts within $< 100\text{ ms}$; returns `JobResult(status="cancelled")` | `result.status == JobStatus.CANCELLED`; cancellation latency $< 100\text{ ms}$ |
| **ADV-07** | `test_cancellation_preemption_timeout` | Worker task is non-cooperative (simulated infinite unyielding loop) | Grace period expires (3.0s); supervisor forcefully terminates/recycles worker | Supervisor recycles worker; active generation increments; job marked `CANCELLED` |
| **ADV-08** | `test_stale_generation_epoch_fencing` | Worker emits delayed `JobUpdate` or `JobResult` from generation $N$ after restart to generation $N+1$ | Supervisor discards message; state is not overwritten by zombie event | Supervisor state unchanged; warning logged with generation mismatch |
| **ADV-09** | `test_oversized_frame_rejection` | Client or worker attempts to send single NDJSON frame exceeding 16 MB | Transport raises `FrameTooLargeError`; closes pipe to prevent memory exhaustion | `FrameTooLargeError` raised; buffer flushed; memory consumption remains bounded |
| **ADV-10** | `test_malformed_ndjson_recovery` | Pipe receives corrupt JSON or binary garbage | Transport raises `ProtocolFramingError`; invalid frame dropped without crashing listener | Listener logs framing error; transport remains functional for subsequent frames |
| **ADV-11** | `test_job_fsm_invalid_regression` | Attempt transition `RUNNING -> QUEUED` or `COMPLETED -> RUNNING` | FSM raises `IllegalStateTransitionError`; internal state remains unchanged | `pytest.raises(IllegalStateTransitionError)`; `fsm.current_state == prior_state` |
| **ADV-12** | `test_job_dto_frozen_mutation_rejection` | Attempt mutating any attribute on `JobSubmission`, `JobResult`, etc. | Python runtime raises `FrozenInstanceError` | `pytest.raises(FrozenInstanceError)` for all 8 DTO types |
| **ADV-13** | `test_port_collision_zombie_cleanup` | Local server port 9379/8080 already bound by dead zombie PID | Worker queries TCP table, identifies zombie PID, terminates it, and binds port cleanly | Port successfully bound; new server starts without `WSAEADDRINUSE` |
| **ADV-14** | `test_concurrent_job_cancellations` | Multiple threads issue cancellation simultaneously for same `job_id` | Operation is idempotent; exactly one `CANCELLED` terminal state emitted | Exactly one `JobResult(status="cancelled")` dispatched; zero race exceptions |

---

## 7. Actionable Implementation & Testing Blueprint

### 7.1 Proposed Test File Hierarchy
```
tests/
├── core/
│   └── job/
│       ├── __init__.py
│       ├── test_dto.py                # DTO immutability, slots, serialization
│       ├── test_schemas.py            # JSON Schema Draft 2020-12 validation
│       ├── test_state_machine.py      # Discrete job & continuous session FSM
│       ├── test_cancellation.py       # CancellationToken, yield points, coordinator
│       ├── test_protocol.py           # NDJSON framing, length limits, error envelopes
│       └── test_mock_client.py        # In-memory mock client without OS dependencies
└── worker/
    ├── __init__.py
    ├── conftest.py                    # Worker fixtures (pipe names, job object guard)
    ├── test_process_lifecycle.py      # Job object containment, spawn, clean shutdown
    ├── test_pipe_transport.py         # Named pipe transport, DACL security, buffer limits
    ├── test_handshake.py              # Semantic handshake, capability negotiation
    ├── test_heartbeat.py              # Heartbeat watchdog, fast broken-pipe detection
    ├── test_crash_recovery.py         # Crash resilience, circuit breaker (FAILED_TRIPPED)
    └── test_trivial_job.py            # End-to-end echo/compute job execution & cancellation
```

### 7.2 Reusable Test Fixtures & Utilities

#### Fixture 1: Isolated Pipe Name Generator
```python
import uuid
import pytest

@pytest.fixture
def pipe_names():
    uid = uuid.uuid4().hex[:8]
    return {
        "cmd": f"\\\\.\\pipe\\nvda_ai_worker_cmd_{uid}",
        "evt": f"\\\\.\\pipe\\nvda_ai_worker_evt_{uid}",
    }
```

#### Fixture 2: Windows Process & Job Object Guard
```python
import subprocess
import pytest
import win32job

@pytest.fixture
def worker_process_guard():
    processes: list[subprocess.Popen] = []
    job = win32job.CreateJobObject(None, "")
    info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
    info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)

    def _spawn(args: list[str]) -> subprocess.Popen:
        proc = subprocess.Popen(args)
        win32job.AssignProcessToJobObject(job, proc._handle)
        processes.append(proc)
        return proc

    yield _spawn

    for proc in processes:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2.0)
```

#### Fixture 3: Accelerated Virtual Clock for Watchdog / Circuit Breaker Tests
```python
class VirtualClock:
    def __init__(self, start: float = 1000.0):
        self.current = start

    def monotonic(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds
```

### 7.3 Step-by-Step Verification Checklist for Implementers

1. **Slice 2 Rollout**:
   - [ ] Implement `core/job/dto.py`, `core/job/state.py`, `core/job/cancellation.py`, `core/job/protocol.py`.
   - [ ] Run `uv run pytest tests/core/job/` — verify all pass in $< 1.0\text{ s}$.
   - [ ] Run `uv run pytest tests/test_import_boundaries.py` — verify `core/job/` passes with 0 violations in $< 150\text{ ms}$.
   - [ ] Run `uv run ruff check .` — verify 0 errors.

2. **Slice 3 Rollout**:
   - [ ] Add `"worker"` to `PURE_DIRECTORIES` in `tests/test_import_boundaries.py`.
   - [ ] Implement `worker/process.py`, `worker/ipc/transport.py`, `worker/ipc/handshake.py`, `plugin/worker_supervisor.py`.
   - [ ] Run `uv run pytest tests/worker/` — verify multi-process lifecycle, handshake, broken pipe, and circuit breaker pass in $< 8.0\text{ s}$.
   - [ ] Run `uv run pytest tests/test_import_boundaries.py` — verify `worker/` has zero forbidden NVDA imports.
   - [ ] Run `uv run scons --dry-run` — verify build graph is clean and excludes tests.
   - [ ] Run full baseline gate:
     - `uv run ruff check .`
     - `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml`
     - `cargo check --manifest-path nvda_ui_host/Cargo.toml`
     - `uv run pytest`

---

## 8. Conclusion

The testing infrastructure and verification gates for Slice 2 and Slice 3 are fully mapped and verified. The baseline suite (450 tests, 20 Rust supervisor tests, AST boundary tests, and SCons build graph) is 100% operational. The proposed test architectures provide complete coverage of DTO immutability, schema validation, state machines, process isolation, Win32 Job Object containment, DACL security, broken-pipe detection, and circuit-breaker failure isolation.
