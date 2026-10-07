## 2026-10-05T04:46:17Z
You are Worker 3 (Slice 3 Implementation Specialist) for Migration Slice 2 & Slice 3 of adil-adysh/NVDA-AI-assistant.
Your working directory is: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\worker_slice3

MANDATORY FIRST STEP:
Read D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\ORIGINAL_REQUEST.md in full. Do not skip or summarize.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

INPUTS:
- Authoritative User Request: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\ORIGINAL_REQUEST.md (see timestamp 2026-10-05T01:52:03Z)
- Approved Architecture Deliverable: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\architecture_deliverable.md (Sections 1.2, 2.1-2.3, 14, 17 Slice 3, 21.1, Invariants A16-A20, A26)
- Project Scope Document: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\orchestrator_slice2_3_gen2\PROJECT.md
- Explorer 2 Survey Report: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\explorer_slice3_survey\report.md
- Explorer 3 Survey Report: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\explorer_test_survey\report.md
- Implemented Slice 2 modules in `addon/globalPlugins/AI-assistant/core/job/`
- Existing test bootstrap: `tests/support/bootstrap.py` and `tests/test_import_boundaries.py`

FILE OWNERSHIP (You exclusively own and may create/modify these files):
- `ai_assistant_worker.py`
- `addon/globalPlugins/AI-assistant/worker/__init__.py`
- `addon/globalPlugins/AI-assistant/worker/job_object.py`
- `addon/globalPlugins/AI-assistant/worker/ipc/__init__.py`
- `addon/globalPlugins/AI-assistant/worker/ipc/security.py`
- `addon/globalPlugins/AI-assistant/worker/ipc/transport.py`
- `addon/globalPlugins/AI-assistant/worker/server.py`
- `addon/globalPlugins/AI-assistant/plugin/worker_supervisor.py`
- `addon/globalPlugins/AI-assistant/service/worker_client.py`
- `tests/test_import_boundaries.py` (add `"worker"` to `PURE_DIRECTORIES`)
- `tests/worker/__init__.py`
- `tests/worker/test_job_object.py`
- `tests/worker/test_pipe_transport.py`
- `tests/worker/test_handshake.py`
- `tests/worker/test_heartbeat.py`
- `tests/worker/test_crash_recovery.py`
- `tests/worker/test_trivial_job.py`
- `tests/worker/test_supervisor.py`

TASK SPECIFICATION:
Implement Milestone 2 (Slice 3: Supervised Worker Process Lifecycle, Named Pipes, Failure Isolation, Heartbeat, and Circuit Breaker) with 100% genuine code and complete test coverage:

1. Win32 Job Object Containment (`worker/job_object.py`):
   - Configure Win32 Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (0x2000) and `JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION` (0x0400).
   - Implement with `pywin32` (`win32job`, `win32api`) with a ctypes Win32 fallback.
   - Functions: `create_worker_job_object() -> JobObject`, `assign_process_to_job(job_obj, process_handle)`. Guarantees zero orphaned child processes on parent crash or kill.

2. Win32 Security DACL (`worker/ipc/security.py`):
   - Create security descriptor with DACL granting `GENERIC_READ | GENERIC_WRITE | SYNCHRONIZE` strictly to `TOKEN_USER` (current user SID) and `Administrators` (RID 544). Reject unauthorized local accounts.

3. Named Pipe Transport (`worker/ipc/transport.py`):
   - Bi-directional Windows Named Pipe client/server communication:
     `cmd` pipe (`\\.\pipe\nvda_ai_worker_cmd`) and `evt` pipe (`\\.\pipe\nvda_ai_worker_evt`).
     Support dynamic pipe name suffix (e.g. `cmd_pipe_name`, `evt_pipe_name`) so tests can run concurrently with unique isolated pipe names.
     NDJSON frame encoding/decoding using `core/job/protocol.py`.
     Fast broken-pipe detection (< 5 ms latency on `ERROR_BROKEN_PIPE` / 109).

4. Worker Executable Entrypoint & Server (`ai_assistant_worker.py` & `worker/server.py`):
   - Root executable `ai_assistant_worker.py` runnable via `python ai_assistant_worker.py` or `uv run ai_assistant_worker.py` with CLI arguments (`--cmd-pipe`, `--evt-pipe`, `--parent-pid`).
   - `WorkerServer`:
     Spawns command listener thread and event broadcaster.
     Parent watchdog: monitors parent process; cleanly exits if parent PID terminates.
     Built-in trivial compute / echo job executor: streams multi-step progress updates, checks `CancellationToken` at yield points, returns terminal `JobResult`.
     Built-in ping/heartbeat responder.
     AST boundary: zero NVDA imports!

5. NVDA-side Lifecycle Supervisor (`plugin/worker_supervisor.py`):
   - `WorkerSupervisor`:
     Spawns worker process assigned to Windows Job Object.
     Exchanges versioned handshake (`v1.0.0`). Rejects incompatible versions.
     Monotonic 5.0s heartbeat probe and 15.0s liveness timeout.
     Fast broken-pipe crash detection.
     Circuit breaker: exponential backoff restart ($1\text{s}, 2\text{s}, 4\text{s} \dots \le 10\text{s}$), tripping after $\ge 3$ crashes within 60s to `FAILED_TRIPPED`, halting restart loops and notifying presenter via callback (`nvda_ui.message`).
     Diagnostic 64 KB stderr ring buffer (RS-08).
     Fast graceful shutdown sequence (< 1.5s).

6. Concrete Client (`service/worker_client.py`):
   - `NamedPipeWorkerClient` and `JobClient` connecting to supervisor and named pipes, implementing the pure-Python `WorkerClient` and `JobClient` abstract interfaces from Slice 2.

7. Import Boundary Enforcement (`tests/test_import_boundaries.py`):
   - Add `"worker"` to `PURE_DIRECTORIES` tuple in `tests/test_import_boundaries.py` and verify zero forbidden imports.

8. Comprehensive Tier 2 Unit & Integration Tests under `tests/worker/`:
   - `test_job_object.py`: Job object creation, limit setting, process assignment.
   - `test_pipe_transport.py`: Named pipe connect, NDJSON round-trip, broken pipe detection < 5ms.
   - `test_handshake.py`: Handshake accepted vs rejected incompatible version.
   - `test_heartbeat.py`: 5.0s ping, 15.0s timeout detection.
   - `test_crash_recovery.py`: Kill worker while idle, kill worker during active job, circuit breaker tripping after >=3 rapid crashes to `FAILED_TRIPPED`, verifying NVDA thread never freezes or hangs.
   - `test_trivial_job.py`: Submit trivial compute job over named pipes, stream progress, verify completion, test cancellation.
   - `test_supervisor.py`: Supervisor launch, handshake, graceful shutdown.

REQUIRED VERIFICATION BEFORE HANDOFF:
1. `uv run ruff check .` (0 errors)
2. `uv run pytest tests/test_import_boundaries.py` (Must pass, 0 violations in worker/)
3. `uv run pytest tests/core/job/` (Must pass)
4. `uv run pytest tests/worker/` (Must pass)
5. `uv run pytest -m "not nvda_integration"` (All pass, 0 regressions)
