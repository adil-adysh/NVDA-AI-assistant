# Project: Migration Slice 2 & Slice 3 (Job Domain & Supervised Worker IPC) - Final Verification & Gate Sign-off

## Architecture
- **Layer 2 (Pure Python Domain)**: `addon/globalPlugins/AI-assistant/core/job/`
  - Zero NVDA dependencies.
  - Frozen `@dataclass(frozen=True, slots=True)` DTOs (`JobId`, `JobSpec`, `JobSnapshot`, `JobProgress`, `JobResult`, `JobFailure`, `JobState`, `JobSubmission`, `JobUpdate`, `JobStatus`, `HandshakeRequest`, `HandshakeResponse`, `SessionConfig`, `StreamChunk`, `WorkerHealth`).
  - Draft 2020-12 JSON Schema validation with pure standard library validator (`schemas.py`).
  - Discrete monotonic Job FSM (`SUBMITTED` -> `QUEUED` -> `RUNNING` -> terminal `COMPLETED`/`FAILED`/`CANCELLED`) with strict state transition validation and terminal immutability; continuous Session FSM (`state.py`).
  - Two-phase cancellation contract: cooperative yield token checking (`CancellationToken`) + supervisor preemption timeout (`cancellation.py`).
  - Versioned wire protocol (`v1.0.0`), NDJSON / hybrid binary framing, semantic handshake, and typed error catalog (`protocol.py`).
  - Abstract `JobClient` and `WorkerClient` interfaces with in-memory mocks (`client.py`).
- **Layer 3 (Out-of-Process Worker Engine)**: `addon/globalPlugins/AI-assistant/worker/` and `ai_assistant_worker.py`
  - Dedicated worker executable entrypoint (`ai_assistant_worker.py`) enclosed in Windows Job Object (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, `JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION`).
  - Duplex Windows Named Pipes (`\\.\pipe\nvda_ai_worker_cmd` and `\\.\pipe\nvda_ai_worker_evt`) with Win32 user-SID DACL security (`ipc/security.py`, `ipc/transport.py`).
  - Multi-threaded worker server (`worker/server.py`): command dispatch, event streaming broadcast, parent watchdog, built-in echo/ping and multi-step trivial compute job executors.
- **Layer 1 (Application Orchestration & Supervision)**:
  - NVDA-side `WorkerSupervisor` in `addon/globalPlugins/AI-assistant/plugin/worker_supervisor.py`: process launch, Job Object assignment, semantic handshake, monotonic 5.0s heartbeat, 15.0s liveness timeout, fast broken-pipe detection (<5ms), diagnostic 64 KB stderr ring buffer, exponential backoff restart, circuit breaker tripping (>= 3 crashes within 60s -> `FAILED_TRIPPED`), speech error notification.
  - Concrete `NamedPipeWorkerClient` in `addon/globalPlugins/AI-assistant/service/worker_client.py`.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F1 | Immutable Job DTOs & Enums | Frozen dataclasses with slots (`JobId`, `JobSpec`, `JobSnapshot`, `JobProgress`, `JobResult`, `JobFailure`, `JobState`, etc.) with JSON serialization | M1 (Slice 2) | ORIGINAL_REQUEST §R1, Deliverable §16.1 |
| F2 | Draft 2020-12 JSON Schema Validation | Formal JSON Schema specs and pure standard library schema validator with zero external dependencies | M1 (Slice 2) | ORIGINAL_REQUEST §R1, Deliverable §16.2 |
| F3 | Monotonic Job & Session FSMs | Monotonic transitions (`SUBMITTED` -> `QUEUED` -> `RUNNING` -> terminal `COMPLETED`/`FAILED`/`CANCELLED`), terminal immutability, single-result invariant | M1 (Slice 2) | ORIGINAL_REQUEST §R1, Deliverable §15.1, §15.3 |
| F4 | Two-Phase Cancellation Contract | Cooperative `CancellationToken` checked at yield points + 3.0s supervisor preemption escalation | M1 (Slice 2) | ORIGINAL_REQUEST §R1, Invariant A22, Deliverable §15.2 |
| F5 | Versioned Wire Protocol & Framing | Protocol `v1.0.0`, NDJSON control plane framing, hybrid binary streaming framing, handshake capability negotiation, typed error catalog | M1 (Slice 2) | ORIGINAL_REQUEST §R1, Invariants A17, A18, A20 |
| F6 | Pure-Python Client Interfaces & Mocks | Abstract `JobClient` and `WorkerClient` interfaces, in-memory `MockJobClient` and `MockWorkerClient` for Tier 1 isolated testing | M1 (Slice 2) | ORIGINAL_REQUEST §R1, Deliverable §14 |
| F7 | Worker Process Executable & Server | Dedicated worker entrypoint `ai_assistant_worker.py` and `worker/server.py` runnable via python/uv with clean AST import boundaries | M2 (Slice 3) | ORIGINAL_REQUEST §R2, Deliverable §2.1 |
| F8 | Windows Job Object Containment | Win32 Job Object with `KILL_ON_JOB_CLOSE` & `DIE_ON_UNHANDLED_EXCEPTION` via pywin32 with ctypes fallback | M2 (Slice 3) | ORIGINAL_REQUEST §R2, Invariants A16, A26 |
| F9 | Bi-Directional Named Pipe Transport | Duplex Named Pipes (`cmd` & `evt`) with secure user-SID DACL permissions and <5ms broken pipe detection | M2 (Slice 3) | ORIGINAL_REQUEST §R2, Invariant A18 |
| F10 | NVDA-Side Worker Lifecycle & Supervision | `WorkerSupervisor` with handshake, 5.0s monotonic heartbeat, 15.0s timeout, diagnostic 64 KB stderr ring buffer, fast graceful shutdown | M2 (Slice 3) | ORIGINAL_REQUEST §R2, Invariant A19 |
| F11 | Circuit Breaker & Exponential Backoff | Exponential restart backoff, circuit breaker tripping after >=3 crashes in 60s (`FAILED_TRIPPED`), halting restart loop, user notification | M2 (Slice 3) | ORIGINAL_REQUEST §R2, Invariant A20 |
| F12 | Built-in Echo/Ping & Trivial Compute Job | Trivial jobs executed on worker proving end-to-end IPC submission, progress streaming, completion, and cancellation | M2 (Slice 3) | ORIGINAL_REQUEST §R2, Deliverable §17 |
| F13 | Zero-Regression Verification Gate | Ruff: 0 errors; Cargo test: 20/20; Cargo check: clean; AST boundaries passing; 562+ existing tests passing | M3 (Gate) | ORIGINAL_REQUEST §R3 |
| F14 | Failure Isolation & Adversarial Resilience | Worker kill during active job or idle state leaves NVDA responsive sub-50ms with clean reconnection or error reporting (Invariant A19) | M3 (Gate) | ORIGINAL_REQUEST §R3 |
| F15 | Forensic Integrity & Authenticity | 100% genuine implementations, zero cheating/hardcoding/facades, verified via forensic audit | M3 (Gate) | Mandatory Policy |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Slice 2: Job Domain & Versioned Protocol | F1, F2, F3, F4, F5, F6 (`core/job/` DTOs, schemas, FSM, cancellation, protocol, mock clients) | none | VERIFYING |
| M2 | Slice 3: Worker Process Lifecycle & IPC | F7, F8, F9, F10, F11, F12 (`worker/`, `ai_assistant_worker.py`, `WorkerSupervisor`, named pipes, heartbeat, circuit breaker, trivial jobs) | M1 | VERIFYING |
| M3 | Zero-Regression & Failure Isolation Gate | F13, F14, F15 (adversarial stress testing, full suite regression, forensic integrity audit) | M1, M2 | VERIFYING |

## Interface Contracts
### `core/job/` ↔ `worker/` & `plugin/worker_supervisor.py`
- DTOs: `JobSpec`, `JobProgress`, `JobResult`, `JobFailure`, `JobState`, `HandshakeRequest`, `HandshakeResponse`, `WorkerHealth`.
- Protocol Framing: NDJSON control frames (`\n` terminated UTF-8 JSON) and 12-byte header binary frames (`0xAA 0x55 0x01 0x00` + JSON header len + binary len).
- Pipe Names: `\\.\pipe\nvda_ai_worker_cmd`, `\\.\pipe\nvda_ai_worker_evt` (or isolated dynamic names with instance suffix in tests).
- Handshake: Request `HandshakeRequest(protocol_version="1.0.0", client_name="nvda_ai_assistant", ...)`, response `HandshakeResponse(accepted=True, protocol_version="1.0.0", ...)`.
- Cancellation: `CancellationToken.cancel()`, `is_cancelled` check at yield points; `JobCancellationRequest(job_id=...)` sent over command pipe.

### `worker/` ↔ OS Kernel
- Job Object: Windows Job Object handle configured with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (0x2000) and `JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION` (0x0400). Assigned via `AssignProcessToJobObject`.
- Security DACL: Windows Security Descriptor with DACL granting `GENERIC_READ | GENERIC_WRITE | SYNCHRONIZE` exclusively to current user SID (`TOKEN_USER`) and `Administrators` (RID 544).

## Code Layout
- `addon/globalPlugins/AI-assistant/core/job/`:
  - `__init__.py`
  - `dto.py`
  - `schemas.py`
  - `state.py`
  - `cancellation.py`
  - `protocol.py`
  - `client.py`
- `addon/globalPlugins/AI-assistant/worker/`:
  - `__init__.py`
  - `job_object.py`
  - `ipc/`: `__init__.py`, `security.py`, `transport.py`
  - `server.py`
- `ai_assistant_worker.py`: root entrypoint.
- `addon/globalPlugins/AI-assistant/plugin/worker_supervisor.py`
- `addon/globalPlugins/AI-assistant/service/worker_client.py`
- `tests/core/job/`: Tier 1 pure Python tests.
- `tests/worker/`: Tier 2 multi-process worker IPC tests.
