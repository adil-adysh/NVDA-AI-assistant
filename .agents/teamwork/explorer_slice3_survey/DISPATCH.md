## 2026-10-05T03:30:43Z

You are Explorer 2 (Slice 3 Survey Specialist) for Migration Slice 2 & Slice 3 of adil-adysh/NVDA-AI-assistant.
Your working directory is: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\explorer_slice3_survey

MANDATORY FIRST STEP:
Read D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\ORIGINAL_REQUEST.md in full. Do not skip or summarize.

INPUTS:
- Authoritative User Request: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\ORIGINAL_REQUEST.md (see timestamp 2026-10-05T01:52:03Z)
- Approved Architecture Deliverable: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\architecture_deliverable.md (Sections 1.2, 2.1-2.3, 14.1-14.4, 17 Slice 3, 21.1, 24 FW-01..10, TA-09, Invariants A16-A20, A26)
- Existing runtime supervisor and UI host code: `runtime_supervisor/`, `nvda_ui_host/`, `ui/host_process.py`, `ui/host_transport.py`
- Environment & dependencies: `pyproject.toml` (note `pywin32==311` is available)

TASK:
Conduct an exhaustive technical survey of Migration Slice 3: Supervised Worker Process Lifecycle, Named Pipes, and Failure Isolation.
1. Worker Executable / Entrypoint:
   Design `ai_assistant_worker.py` (runnable via `python` / `uv run`) and worker server architecture.
   Specify how the worker runs out-of-process, initializes its command & event pipes, and loops.
2. Windows Job Object Containment (Invariants A16, A26):
   Investigate how `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` and `JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION` are created and assigned to the worker process using `pywin32` (`win32job`, `win32api`) or `ctypes`.
   Ensure zero orphaned child processes on abnormal NVDA crash or Task Manager kill.
3. Named Pipe Transport (Invariant A18):
   Detail bi-directional Windows Named Pipe client/server communication:
   - Command pipe: `\\.\pipe\nvda_ai_worker_cmd`
   - Event pipe: `\\.\pipe\nvda_ai_worker_evt`
   - Win32 security DACL: restricts access strictly to the current user SID (`TOKEN_USER`) and Administrators (`win32security` or `ctypes`).
   - Framing: NDJSON control plane and stream framing.
4. Lifecycle, Heartbeat & Supervision (Invariant A19):
   Design NVDA-side `WorkerSupervisor`:
   - Process launch and Job Object assignment.
   - Versioned handshake exchange.
   - Monotonic 5.0s heartbeat probe and 15.0s liveness timeout.
   - Fast (<5ms) broken-pipe detection (`ERROR_BROKEN_PIPE` / `109`).
   - Graceful shutdown sequence.
5. Circuit Breaker & Recovery (Invariant A20):
   - Exponential backoff restart policy.
   - Circuit breaker tripping after >= 3 crashes within 60s (`FAILED_TRIPPED`).
   - HALT restart loop on tripped state and notify presenter/user.
6. End-to-End Trivial Job:
   - Built-in echo/ping job and trivial compute job (e.g. counting/progress simulation) proving end-to-end IPC submission, progress streaming, completion, and cancellation.

OUTPUT:
Write your complete survey report to:
`D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\explorer_slice3_survey\report.md`
Then call `send_message` to recipient `eb8f4e3d-cb67-4981-b12a-2c54cfb91f1d` with your summary.
Do NOT modify production code. This is a read-only investigation.
