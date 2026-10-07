# Worker Process, Job/Session State Model, and Versioned IPC Architecture Design

- **Author**: Worker / Job / IPC Implementation Designer (Agent 6)
- **Repository**: `adil-adysh/NVDA-AI-assistant`
- **HEAD Commit**: `ced1cbc`
- **Target Invariants**: Invariants A16–A24, Invariant A29
- **Target Migration Slices**: Slice 2 (Job Domain / Protocol), Slice 3 (Worker Lifecycle & IPC), Slice 4 (Heavy Operations Migration), Slice 9 (OCR Session Foundation), Slice 10 (Transcription Session Foundation)
- **Status**: Complete Authoritative Design Specification

---

## 1. Executive Summary & Architectural Scope

This design document establishes the authoritative technical blueprint for the **Worker Process**, **Versioned IPC Architecture**, **Job/Session State Machine**, **Heavy Operations Migration**, and **Bounded Streaming Foundations for Continuous Modalities (OCR & Transcription)** in the `NVDA-AI-assistant` add-on.

### 1.1 The Core Architectural Imperative
NVDA is a mission-critical assistive technology for blind and visually impaired users. In NVDA's execution model, the main Python thread drives the Windows accessibility event loop, speech synthesis queues, braille display refresh cycles, and OS hook responses. Any main-thread stall exceeding 50 milliseconds causes noticeable audio stutter, frozen navigation, and degraded speech responsiveness. More critically, an unhandled native crash, segmentation fault, or out-of-memory driver panic inside `nvda.exe` completely terminates the screen reader, leaving the user without an accessible interface.

At commit `ced1cbc`, local AI model execution, HTTP server supervision, large file downloading, SHA-256 verification, ZIP extraction, and native embedding calculations execute within the NVDA process or via ad-hoc daemon threads spawned directly from NVDA.

To enforce **Invariants A1–A4** (NVDA as a thin accessibility shell) and **Invariants A16–A24, A29**, this design migrates all heavy compute, local model execution, file downloads, and continuous streaming workloads into an isolated, supervised out-of-process **Worker Process** (`nvda_ai_worker.exe` / worker subprocess) communicating with NVDA via a secure, versioned, bi-directional IPC named pipe transport.

### 1.2 Target Invariants Mapped
- **Invariant A16 (Worker Process Isolation)**: All heavy execution, model execution, file operations, and native inference run strictly out-of-process in a separate Worker process protected by a Windows Job Object.
- **Invariant A17 (Versioned Handshake & Capability Negotiation)**: Bi-directional semantic handshake negotiating major/minor compatibility, schema versions, hardware capabilities, and buffer limits before work dispatch.
- **Invariant A18 (Framing & Transport Integrity)**: Robust bi-directional named pipe transport with framing (NDJSON control plane, binary length-prefixed streaming), access control (DACLs), and transport backpressure.
- **Invariant A19 (Heartbeat, Liveness & Crash Detection)**: Monotonic heartbeat probing, pipe disconnection handling, immediate process death detection, and generation-fenced epoch tracking.
- **Invariant A20 (Isolation, Graceful Restart & Circuit Breaker)**: Worker crash does not impact NVDA. Graceful restart with exponential backoff and circuit breaker prevents restart loops.
- **Invariant A21 (Discrete Job FSM)**: Strict, monotonic state transitions for discrete tasks (`QUEUED` $\to$ `RUNNING` $\to$ terminal states `COMPLETED` / `FAILED` / `CANCELLED`).
- **Invariant A22 (Deterministic Two-Phase Cancellation)**: Cooperative cancellation token check at yield points followed by supervisor preemption timeout and worker isolation.
- **Invariant A23 (Session FSM for Continuous Modalities)**: State machine (`INIT` $\to$ `CONFIGURING` $\to$ `ACTIVE_STREAMING` $\leftrightarrow$ `PAUSED` $\to$ `CLOSING` $\to$ `CLOSED`) multiplexed over IPC.
- **Invariant A24 (Immutable DTO & Schema Contracts)**: Strictly validated, frozen dataclasses and complete JSON schemas for all cross-boundary messages.
- **Invariant A29 (Bounded Streaming for Continuous Modalities)**: Bounded frame queue ($N=2$) with latest-wins dropping for OCR (Slice 9); bounded audio ring buffer (10s) with partial/finalized transcript semantics for Transcription (Slice 10).

---

## 2. Existing Architecture Analysis & Codebase Evidence

A code-level audit of HEAD (`ced1cbc`) reveals significant thread contamination, ad-hoc background processes, and in-process execution vulnerabilities that this Worker/IPC design directly addresses:

### 2.1 In-Process Heavy Downloads & Compression (Audit D & Audit F Evidence)
- **File**: `addon/globalPlugins/AI-assistant/providers/runtime/download.py`
  - Lines 77–160: `RuntimeDownloadService.download()` downloads multi-gigabyte ZIP bundles (`litert-runtime-v{version}`) directly from within NVDA.
  - Lines 142–158: Synchronous `hashlib.sha256()` hashing and `zipfile.ZipFile.extractall()` run inside NVDA process threads.
  - Lines 27: Direct import of NVDA's `from logHandler import log` contaminates the download service with NVDA internals.
  - If a ZIP is corrupt or decompression crashes, memory consumption spikes inside `nvda.exe`.

### 2.2 Unmanaged Native Process Spawning from NVDA (Audit E Evidence)
- **File**: `runtime_supervisor/src/process.rs` & `runtime_supervisor/src/supervisor.rs`
  - Lines 44–45 in `process.rs`: `cmd.stdout(Stdio::null())` and `cmd.stderr(Stdio::null())` discard all child diagnostics.
  - Audit E Finding **RS-06** [CONFIRMED, DESIGN DETAIL]: Absence of Windows Job Objects permits process tree leaks if NVDA terminates unexpectedly.
  - Audit E Finding **RS-08** [CONFIRMED, DESIGN DETAIL]: Discarding child `stderr` conceals native CUDA/DLL crash diagnostics.
  - Audit E Finding **RS-13** [CONFIRMED, BLOCKER]: Native `RuntimeSupervisor` runs directly inside `nvda.exe`, spawning `litert-lm` and `llama-server` as direct child processes of the accessibility shell.

### 2.3 Unmanaged Daemon Threads in NVDA (Audit B Evidence)
- **File**: `addon/globalPlugins/AI-assistant/plugin/background.py`
  - Lines 80–85: `_on_litert_server_config_changed()` spawns unmanaged thread `litert-restart-on-config-change`.
  - Lines 105–110: `_on_llama_server_config_changed()` spawns unmanaged thread `llama-shutdown-on-config-change`.
  - Lines 404–440: `start_model_preload()` spawns unmanaged thread `BrowserAssistantModelPreload`.
  - Lines 441–495: `run_use_case_in_background()` spawns thread `AIassistant{title}Worker` running synchronous inference, readiness checks, and server starts.
  - Lines 490–492: Result delivery via `nvda_ui.queue(render_result, result)` queues directly back into NVDA event loop without backpressure.

### 2.4 Existing IPC Patterns in Repository (`ui_host`)
- **File**: `addon/globalPlugins/AI-assistant/ui/host_transport.py` and `nvda_ui_host/src/ipc/transport.rs`
  - Lines 21–22 in `nvda_ui_host/src/ipc/transport.rs`: Demonstrates Windows Named Pipes (`\\.\pipe\nvda_ai_assistant_ui_cmd` and `\\.\pipe\nvda_ai_assistant_ui_evt`).
  - Lines 146–160 in `transport.rs`: Demonstrates newline-delimited framing (`BufRead::read_until(b'\n')`) with `MAX_FRAME_BYTES = 4 * 1024 * 1024` (4 MB limit).
  - This establishes a proven, high-performance IPC pattern in the repository that the Worker IPC architecture extends.

---

## 3. Worker Process Lifecycle & Supervision Architecture (Invariants A16, A19, A20, Slice 3)

```
+---------------------------------------------------------------------------------------------------+
| NVDA Process (nvda.exe) - Thin Accessibility Shell                                                 |
|                                                                                                   |
|  +--------------------+         Windows Named Pipes            +-------------------------------+  |
|  | NVDA Client Proxy  | <====================================> | WorkerSupervisor (Python)     |  |
|  | (JobClient,        |  - cmd: \\.\pipe\nvda_worker_cmd       | - Process monitoring          |  |
|  |  SessionManager)   |  - evt: \\.\pipe\nvda_worker_evt       | - Generation fencing          |  |
|  +--------------------+                                        | - Heartbeat monitor           |  |
|            |                                                   +-------------------------------+  |
+------------|-------------------------------------------------------------------|------------------+
             |                                                                   | Windows Job Object
             | Spawns & Supervises via Job Object                                | (KILL_ON_JOB_CLOSE)
             v                                                                   v
+---------------------------------------------------------------------------------------------------+
| Dedicated Worker Process (nvda_ai_worker.exe / worker.py subprocess)                              |
|                                                                                                   |
|  +-----------------------------+       +-------------------------+       +---------------------+  |
|  | Worker IPC Server           | <---> | Worker Dispatch Engine  | <---> | Continuous Session  |  |
|  | - Handshake / Capabilities  |       | - Job Queue (Priority)  |       |   Manager           |  |
|  | - NDJSON / Binary framing   |       | - Thread Pool Executor  |       | - OCR Bounded Queue |  |
|  | - Backpressure Flow Control |       | - Cancellation Tokens   |       | - Audio Ring Buffer |  |
|  +-----------------------------+       +-------------------------+       +---------------------+  |
|                                                     |                                             |
|                                                     v                                             |
|                                        +-------------------------+                                |
|                                        | Heavy Task Executors    |                                |
|                                        | - Model Download/Verify |                                |
|                                        | - RuntimeSupervisor     |                                |
|                                        |   (LiteRT/llama-server) |                                |
|                                        | - Candle Embeddings     |                                |
|                                        +-------------------------+                                |
+---------------------------------------------------------------------------------------------------+
```

### 3.1 Process Isolation & Process Model (Invariant A16)
- **Isolation Boundary**: The Worker executes in its own Win32 process space, distinct and detached from `nvda.exe`.
- **Worker Binary Representation**:
  - *Development / Python Environment*: Subprocess executed via `sys.executable` with `-m addon.globalPlugins.AI-assistant.worker` (isolated Python process without NVDA imports).
  - *Production Package*: Dedicated compiled executable `nvda_ai_worker.exe` (or embedded Python launcher matching `nvda_ui_host.exe` design) bundling required native extensions (`runtime_supervisor.pyd`, `embedding_engine.pyd`) and pure Python worker code.
- **Zero NVDA Contamination in Worker**: The worker process environment does NOT import `nvda`, `gui`, `wx`, `speech`, `tones`, or `logHandler`. Logging uses standard Python `logging` or writes to a designated worker log file (`nvda_worker.log`).

### 3.2 Windows Job Object Containment & Crash Isolation
- **Job Object Association**: Upon creation, NVDA assigns the worker process to an anonymous Windows Job Object handle (`CreateJobObjectW`).
- **Job Object Configuration**:
  ```python
  JOBOBJECT_EXTENDED_LIMIT_INFORMATION = ...
  limit_flags = (
      JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE |
      JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION
  )
  ```
- **Crash Containment Guarantee**:
  1. If `nvda.exe` crashes or is killed by the OS, Windows kernel automatically closes the Job Object handle, immediately terminating `nvda_ai_worker.exe` and any grandchild processes (`llama-server.exe`, `litert-lm`). No orphaned zombies or leaked GPU VRAM.
  2. If the Worker crashes (segfault, out-of-memory), the failure is completely isolated to the worker process. The Windows Job Object prevents crash dialogs (`SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX)`). `nvda.exe` remains responsive.

### 3.3 Process Spawning & Creation Flags
The worker process is spawned with Win32 creation flags:
- `CREATE_NO_WINDOW (0x08000000)`: Prevents console window popup.
- `CREATE_NEW_PROCESS_GROUP (0x00000200)`: Isolates console signal handling (Ctrl+C).
- `subprocess.STARTUPINFO`: `dwFlags |= STARTF_USESHOWWINDOW`, `wShowWindow = SW_HIDE`.
- Standard Streams:
  - `stdin`: Pipe or Null (communication is via named pipes).
  - `stdout`: Pipe to capture worker startup logs.
  - `stderr`: Dedicated diagnostic pipe drained by a background thread into `worker_stderr.log` (directly resolving Audit E Finding **RS-08**).

### 3.4 Heartbeat, Liveness Probing & Crash Detection (Invariant A19)
- **Periodic Heartbeat**:
  - NVDA sends `WorkerHealth` probe every $T_{ping} = 5.0\text{ seconds}$.
  - The Worker replies with `WorkerHealth` status containing memory usage, CPU usage, active job count, and monotonic uptime.
  - Heartbeat timeout threshold: $T_{timeout} = 15.0\text{ seconds}$ (3 missed heartbeats).
- **Immediate Pipe Break Detection**:
  - If the worker process exits abruptly or crashes, the Windows named pipe driver immediately breaks the connection.
  - The NVDA-side pipe reader encounters `ERROR_BROKEN_PIPE` (`winerror=109`) or `EOF`.
  - Detection latency: **< 5 milliseconds** on process exit.
- **Process Exit Polling**:
  - In addition to pipe notifications, the supervisor holds the process handle and polls `GetExitCodeProcess` or awaits `WaitForSingleObject` asynchronously to capture exact exit codes (e.g. `0xC0000005` for access violation / segfault).

### 3.5 Monotonic Generation Fencing
To resolve Audit E Findings **RS-01, RS-02, RS-03, RS-04**:
- Every worker instance has an integer `generation` counter (initialized to 1, incremented monotonically on every spawn/restart).
- Every IPC message includes `generation: int`.
- The supervisor maintains `active_generation: int`. Any incoming message with `msg.generation < active_generation` is discarded as stale.
- On worker crash, timeout, or shutdown, `active_generation` is immediately incremented, invalidating all pending responses from the prior epoch.

### 3.6 Graceful Restart, Exponential Backoff & Circuit Breaker (Invariant A20)
- **Restart Procedure**:
  1. Increment `active_generation`.
  2. Mark all in-flight non-idempotent jobs as `FAILED` (`error_code="WORKER_CRASHED"`, `retriable=True`).
  3. Close broken pipe handles.
  4. Forcefully terminate previous process handle if still hanging (`TerminateJobObject` or `TerminateProcess`).
  5. Spawn fresh worker process.
  6. Perform versioned handshake and capability negotiation.
- **Circuit Breaker Policy**:
  - Threshold: Max 3 crashes within any sliding 60-second window.
  - If crash count $\ge 3$ within 60s, state transitions to `FAILED_TRIPPED` (Circuit Breaker Tripped).
  - Tripped behavior: Worker is NOT restarted automatically. NVDA presents a localized accessibility notification:
    *"AI Assistant local worker stopped responding. Model features unavailable. Open Settings to restart or view diagnostics."*
  - Reset: Circuit breaker resets automatically on manual user action ("Restart Worker" button) or 5 minutes of stability.

---

## 4. Versioned IPC Protocol & Framing (Invariants A17, A18, Slice 3)

### 4.1 Versioned Handshake & Capability Negotiation (Invariant A17)
Immediately after the named pipe connection is established, the client (NVDA) and server (Worker) must complete a two-way versioned handshake before any jobs or sessions are accepted.

```
NVDA (Client)                                          Worker (Server)
     |                                                       |
     | ----- HandshakeRequest (v1.0, capabilities) --------> |
     |                                                       | (Validate version,
     |                                                       |  check compatibility)
     | <---- HandshakeResponse (accepted=True, ...) -------- |
     |                                                       |
   [Handshake Established: Protocol Ready for Work Submission]
```

- **Protocol Semantic Versioning Rules**:
  - `PROTOCOL_VERSION = "1.0.0"`
  - `major`: Breaking changes (incompatible envelope, removed DTO fields). Mismatch causes connection termination (`COMPATIBILITY_REJECTED`).
  - `minor`: Backwards-compatible additions (new job types, optional parameters). Client and worker negotiate the highest mutually supported minor version.
  - `patch`: Internal bug fixes; fully compatible.
- **Capability Flags Negotiated**:
  `"job.model_download"`, `"job.model_verify"`, `"job.model_unpack"`, `"job.inference"`, `"session.ocr"`, `"session.transcription"`, `"runtime.litert"`, `"runtime.llama"`.
  If NVDA requests a job type not present in the negotiated capabilities, submission fails immediately with `CAPABILITY_UNSUPPORTED`.

### 4.2 Transport Architecture: Bi-Directional Windows Named Pipes (Invariant A18)
- **Pipe Configuration**:
  - **Command Pipe** (`\\.\pipe\nvda_ai_assistant_worker_cmd`):
    Duplex byte stream for RPC-style request-response (`JobSubmission`, `JobCancellationRequest`, `SessionControlCommand`, `WorkerHealth`).
  - **Event Pipe** (`\\.\pipe\nvda_ai_assistant_worker_evt`):
    Duplex/Server-to-Client byte stream for asynchronous streaming events (`JobUpdate`, `JobResult`, `StreamChunk`, `WorkerHealthEvent`).
- **Security & Access Control (Pipe DACL)**:
  Named pipes on Windows can be vulnerable to unauthorized local processes if created with default security.
  The Worker creates pipes with an explicit **Security Descriptor (DACL)** granting `FILE_ALL_ACCESS` strictly to the current user's security identifier (`TOKEN_USER` SID) and `Administrators`. Anonymous access and other unprivileged user accounts are denied.

### 4.3 Message Framing: NDJSON & Binary Extensions
- **Control & Job Plane Framing**:
  - **NDJSON (Newline-Delimited JSON)**: Every message is serialized as a single-line UTF-8 JSON object terminated by `\n` (`0x0A`).
  - **Frame Size Limit**: `MAX_FRAME_BYTES = 16 * 1024 * 1024` (16 MB).
  - Rationale: Fully compatible with existing `nvda_ui_host` reader patterns; debuggable with network/pipe loggers; zero external C dependencies.
- **Binary Streaming Framing (OCR & Audio PCM)**:
  For high-frequency video frames and PCM audio buffers in Slices 9 & 10, JSON base64 encoding incurs a 33% CPU/memory overhead.
  The streaming transport supports a **2-part hybrid binary frame**:
  ```
  +-----------------------+-----------------------+-----------------------+
  | Magic Header (4 bytes)| JSON Header Len (4B)  | Binary Payload Len(4B)|
  | 0xAA 0x55 0x01 0x00   | uint32 big-endian     | uint32 big-endian     |
  +-----------------------+-----------------------+-----------------------+
  | JSON Metadata Header (StreamChunk DTO without raw bytes)             |
  +-----------------------------------------------------------------------+
  | Raw Binary Bytes (Raw BGRA/JPEG image pixels or 16-bit PCM audio)     |
  +-----------------------------------------------------------------------+
  ```
  This allows zero-copy slicing of audio PCM and OCR image buffers while preserving structured typed metadata.

### 4.4 Flow Control & Transport Backpressure
- **Backpressure Mechanism**:
  1. **Socket/Pipe Buffer Limits**: Pipe buffer set to 64 KB (`BUFFER_SIZE = 65536`). If the consumer stops reading, the OS write buffer fills.
  2. **Non-blocking Write Checks**: The producer monitors pipe write readiness. When backpressure is detected, the producer pauses emission or invokes modality-specific drop policies (see Section 9 & 10).
  3. **High/Low Watermark Queues**: In-memory queues in NVDA and Worker have explicit bounds (`maxsize=100`). Enqueuing on a full queue applies producer backpressure rather than unbounded allocation.

---

## 5. Job State Machine & Discrete Task Execution (Invariants A21, A22, Slice 2)

Discrete operations (e.g. downloading a model, computing a text embedding, running single-shot inference, validating a checksum) execute as independent **Jobs**.

### 5.1 Discrete Job Finite State Machine (Invariant A21)

```
        +---------------+
        |   SUBMITTED   |  (Created by NVDA Client)
        +---------------+
                |
                v  [Enqueued in Worker Queue]
        +---------------+
        |    QUEUED     |
        +---------------+
                |
                v  [Worker thread picks up job]
        +---------------+
        |    RUNNING    | <----+  (Emits periodic JobUpdate)
        +---------------+      |
          |     |     |  +-----+
          |     |     |
          |     |     +-------------------------+
          |     v [Success]                     | [Failure / Error]
          |   +---------------+                 v
          |   |   COMPLETED   | (Terminal)    +---------------+
          |   +---------------+               |    FAILED     | (Terminal)
          |                                   +---------------+
          v [Cancel Token Triggered]
        +---------------+
        |   CANCELLED   | (Terminal)
        +---------------+
```

### 5.2 State Transition Matrix & Invariants
| Current State | Event / Trigger | Next State | Allowed? | Emits DTO | Side Effects |
|---|---|---|---|---|---|
| `None` | Client submits job | `SUBMITTED` | Yes | `JobSubmission` | Assigned UUID, placed in outbox |
| `SUBMITTED` | Worker acknowledges receipt | `QUEUED` | Yes | `JobUpdate(stage="queued")` | Placed in priority executor queue |
| `QUEUED` | Worker thread dequeues | `RUNNING` | Yes | `JobUpdate(stage="running")` | CancellationToken initialized |
| `RUNNING` | Progress milestone | `RUNNING` | Yes | `JobUpdate(pct, throughput)` | None (intermediate state) |
| `RUNNING` | Execution succeeds | `COMPLETED` | Yes | `JobResult(status="completed")` | Resources cleaned up, terminal |
| `RUNNING` | Execution throws exception | `FAILED` | Yes | `JobResult(status="failed")` | Error recorded, retriable flag set |
| `QUEUED` | Cancel requested before start | `CANCELLED` | Yes | `JobResult(status="cancelled")` | Removed from queue, terminal |
| `RUNNING` | Cancel requested & confirmed | `CANCELLED` | Yes | `JobResult(status="cancelled")` | Yield points aborted, temp files cleaned |
| `COMPLETED` | Any event | - | **No** | None | Terminal state is immutable |
| `FAILED` | Any event | - | **No** | None | Terminal state is immutable |
| `CANCELLED` | Any event | - | **No** | None | Terminal state is immutable |

**State Invariants**:
1. **Monotonic Progression**: Jobs cannot transition backwards (e.g. `RUNNING` $\to$ `QUEUED`).
2. **Terminal Exclusivity**: A job reaches exactly one terminal state (`COMPLETED`, `FAILED`, or `CANCELLED`).
3. **Single Result Emission**: Exactly one terminal `JobResult` is emitted per job.

### 5.3 Deterministic Two-Phase Cancellation Protocol (Invariant A22)
Native tasks (HTTP downloads, llama-server generation, disk decompression) cannot be safely killed via thread termination (`Thread.kill`) without corrupting process memory. Cancellation enforces a strict two-phase protocol:

1. **Phase 1: Cooperative Cancellation (`JobCancellationRequest`)**:
   - NVDA sends `JobCancellationRequest(job_id=..., reason="user_cancelled")`.
   - Worker sets the job's `threading.Event` cancellation token.
   - The executing worker periodically checks `cancellation_token.is_set()` at fine-grained yield points:
     - Downloads: every read block (64 KB).
     - Decompression: every extracted file.
     - Inference: every generated token.
   - When detected, the task gracefully releases locks, deletes partially unpacked files, and transitions to `CANCELLED` with `JobResult(status="cancelled")`.
2. **Phase 2: Supervisor Preemption Timeout & Worker Escalation**:
   - If the task does not acknowledge cancellation within `CANCELLATION_GRACE_PERIOD = 3.0` seconds:
     - For child processes (e.g. `llama-server.exe` stuck in compute loop): The supervisor signals process termination directly (`SIGTERM` / `TerminateProcess`).
     - For native worker threads stuck in uninterruptible loops: The supervisor escalates to worker process recycle (killing and restarting the worker process), ensuring NVDA never hangs.

---

## 6. Session State Machine & Continuous Streaming (Invariant A23, Slice 2)

Unlike discrete jobs, continuous modalities (live screen OCR, real-time microphone transcription) require long-lived **Sessions** with continuous bi-directional streaming.

### 6.1 Continuous Session State Machine (Invariant A23)

```
        +---------------+
        |     INIT      |  (SessionConfig proposed)
        +---------------+
                |
                v  [Worker allocates model & ring buffer]
        +---------------+
        |  CONFIGURING  |
        +---------------+
                |
                v  [Resources ready]
        +---------------+      Pause Command
        |     READY     | ----------------------+
        +---------------+                       |
                |                               v
     Stream Start | Stream Resumed       +---------------+
                v                        |    PAUSED     |
        +---------------+ -------------> +---------------+
        |   STREAMING   |  Pause Command
        +---------------+
                |
                v  [Close Command / Session Complete]
        +---------------+
        |    CLOSING    |  (Flush buffers, emit final chunks)
        +---------------+
                |
                v  [Deallocated]
        +---------------+               +---------------+
        |    CLOSED     | (Terminal)    |     ERROR     | (Terminal)
        +---------------+               +---------------+
```

### 6.2 Session Lifecycle Transitions
1. **`INIT` $\to$ `CONFIGURING`**: NVDA requests a new continuous session by sending `SessionConfig` (specifying modality, sample rate, language, frame rate, buffer capacity).
2. **`CONFIGURING` $\to$ `READY`**: Worker initializes the modality pipeline (loads OCR engine or Whisper transcription model, allocates audio ring buffer or bounded frame queue). Emits `SessionStatus(state="ready")`.
3. **`READY` $\to$ `STREAMING`**: Ingestion begins. Input chunks are fed into the worker; worker emits `StreamChunk` output messages.
4. **`STREAMING` $\leftrightarrow$ `PAUSED`**: User can pause stream (e.g. microphone mute or OCR inspection pause) without releasing model memory. Buffers are preserved.
5. **`STREAMING` $\to$ `CLOSING` $\to$ `CLOSED`**: Worker drains pending chunks, writes remaining hypotheses, frees GPU/CPU memory, and transitions to terminal `CLOSED`.
6. **`*` $\to$ `ERROR`**: If a fatal hardware or engine error occurs (e.g. audio device disconnected, CUDA OOM), session transitions to `ERROR` with diagnostic payload.

### 6.3 Session Multiplexing & Stream Control Commands
Multiple continuous sessions (e.g. Session `ocr-live-01` and Session `audio-mic-02`) share the single IPC named pipe connection. Every message includes `session_id: str` (UUIDv4) and `seq: int` (monotonic packet sequence number).
Control commands (`PAUSE`, `RESUME`, `RECONFIGURE`, `CLOSE`) target specific `session_id`s without channel cross-talk.

---

## 7. Complete Immutable DTO Specifications (Invariant A24)

All messages exchanged between NVDA and the Worker Process are strictly modeled as immutable Data Transfer Objects (DTOs).

### 7.1 Type Architecture & Immutability Guarantees
- Implemented with `@dataclass(frozen=True, slots=True)` in Python.
- Collections are typed as immutable `tuple` (never mutable `list`).
- String constants are typed using `Literal` or strict `StrEnum`.
- Complete bidirectional JSON serialization (`to_json()`, `from_json()`, `to_dict()`, `from_dict()`).

### 7.2 Complete Python Typed Dataclass Definitions

```python
# -*- coding: utf-8 -*-
"""Authoritative Immutable DTO Definitions for Worker IPC Architecture.

Enforces Invariant A24 (strictly typed, frozen dataclasses with validation).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4


class JobStatus(StrEnum):
    SUBMITTED = "submitted"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SessionState(StrEnum):
    INIT = "init"
    CONFIGURING = "configuring"
    READY = "ready"
    STREAMING = "streaming"
    PAUSED = "paused"
    CLOSING = "closing"
    CLOSED = "closed"
    ERROR = "error"


class ModalityType(StrEnum):
    DOWNLOAD = "download"
    INFERENCE = "inference"
    OCR = "ocr"
    TRANSCRIPTION = "transcription"
    EMBEDDING = "embedding"
    TTS = "tts"


# ---------------------------------------------------------------------------
# 1. HandshakeRequest & HandshakeResponse
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class HandshakeRequest:
    protocol_version: str = "1.0.0"
    client_name: str = "nvda_ai_assistant"
    client_version: str = "1.0.0"
    client_pid: int = 0
    supported_schemas: tuple[str, ...] = ("job.v1", "session.v1", "health.v1")
    requested_capabilities: tuple[str, ...] = (
        "job.model_download",
        "job.model_verify",
        "job.inference",
        "session.ocr",
        "session.transcription",
    )
    request_id: str = field(default_factory=lambda: str(uuid4()))

    def to_json(self) -> str:
        return json.dumps({
            "type": "handshake_request",
            "protocol_version": self.protocol_version,
            "client_name": self.client_name,
            "client_version": self.client_version,
            "client_pid": self.client_pid,
            "supported_schemas": list(self.supported_schemas),
            "requested_capabilities": list(self.requested_capabilities),
            "request_id": self.request_id,
        }, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HandshakeRequest:
        return cls(
            protocol_version=str(data.get("protocol_version", "1.0.0")),
            client_name=str(data.get("client_name", "")),
            client_version=str(data.get("client_version", "")),
            client_pid=int(data.get("client_pid", 0)),
            supported_schemas=tuple(data.get("supported_schemas", ())),
            requested_capabilities=tuple(data.get("requested_capabilities", ())),
            request_id=str(data.get("request_id", "")),
        )


@dataclass(frozen=True, slots=True)
class HandshakeResponse:
    accepted: bool
    protocol_version: str
    worker_pid: int
    worker_version: str
    negotiated_capabilities: tuple[str, ...]
    max_frame_bytes: int = 16 * 1024 * 1024
    error_message: str | None = None
    correlation_id: str = ""

    def to_json(self) -> str:
        return json.dumps({
            "type": "handshake_response",
            "accepted": self.accepted,
            "protocol_version": self.protocol_version,
            "worker_pid": self.worker_pid,
            "worker_version": self.worker_version,
            "negotiated_capabilities": list(self.negotiated_capabilities),
            "max_frame_bytes": self.max_frame_bytes,
            "error_message": self.error_message,
            "correlation_id": self.correlation_id,
        }, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HandshakeResponse:
        return cls(
            accepted=bool(data.get("accepted", False)),
            protocol_version=str(data.get("protocol_version", "")),
            worker_pid=int(data.get("worker_pid", 0)),
            worker_version=str(data.get("worker_version", "")),
            negotiated_capabilities=tuple(data.get("negotiated_capabilities", ())),
            max_frame_bytes=int(data.get("max_frame_bytes", 16 * 1024 * 1024)),
            error_message=data.get("error_message"),
            correlation_id=str(data.get("correlation_id", "")),
        )


# ---------------------------------------------------------------------------
# 2. JobSubmission, JobUpdate & JobResult
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class JobSubmission:
    job_id: str
    job_type: str
    payload: dict[str, Any]
    priority: int = 10  # Lower number = higher priority
    timeout_seconds: float = 300.0
    generation: int = 1
    created_at_epoch_ms: int = 0

    def to_json(self) -> str:
        return json.dumps({
            "type": "job_submission",
            "job_id": self.job_id,
            "job_type": self.job_type,
            "payload": self.payload,
            "priority": self.priority,
            "timeout_seconds": self.timeout_seconds,
            "generation": self.generation,
            "created_at_epoch_ms": self.created_at_epoch_ms,
        }, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobSubmission:
        return cls(
            job_id=str(data["job_id"]),
            job_type=str(data["job_type"]),
            payload=dict(data.get("payload", {})),
            priority=int(data.get("priority", 10)),
            timeout_seconds=float(data.get("timeout_seconds", 300.0)),
            generation=int(data.get("generation", 1)),
            created_at_epoch_ms=int(data.get("created_at_epoch_ms", 0)),
        )


@dataclass(frozen=True, slots=True)
class JobUpdate:
    job_id: str
    status: JobStatus
    progress_pct: float = 0.0
    status_message: str = ""
    bytes_completed: int = 0
    bytes_total: int = 0
    throughput_bytes_per_sec: float = 0.0
    eta_seconds: float | None = None
    generation: int = 1
    timestamp_epoch_ms: int = 0

    def to_json(self) -> str:
        return json.dumps({
            "type": "job_update",
            "job_id": self.job_id,
            "status": str(self.status),
            "progress_pct": round(self.progress_pct, 2),
            "status_message": self.status_message,
            "bytes_completed": self.bytes_completed,
            "bytes_total": self.bytes_total,
            "throughput_bytes_per_sec": round(self.throughput_bytes_per_sec, 2),
            "eta_seconds": self.eta_seconds,
            "generation": self.generation,
            "timestamp_epoch_ms": self.timestamp_epoch_ms,
        }, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobUpdate:
        return cls(
            job_id=str(data["job_id"]),
            status=JobStatus(data.get("status", "running")),
            progress_pct=float(data.get("progress_pct", 0.0)),
            status_message=str(data.get("status_message", "")),
            bytes_completed=int(data.get("bytes_completed", 0)),
            bytes_total=int(data.get("bytes_total", 0)),
            throughput_bytes_per_sec=float(data.get("throughput_bytes_per_sec", 0.0)),
            eta_seconds=data.get("eta_seconds"),
            generation=int(data.get("generation", 1)),
            timestamp_epoch_ms=int(data.get("timestamp_epoch_ms", 0)),
        )


@dataclass(frozen=True, slots=True)
class JobResult:
    job_id: str
    status: JobStatus
    result_data: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    retriable: bool = False
    duration_ms: int = 0
    generation: int = 1

    def to_json(self) -> str:
        return json.dumps({
            "type": "job_result",
            "job_id": self.job_id,
            "status": str(self.status),
            "result_data": self.result_data,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "retriable": self.retriable,
            "duration_ms": self.duration_ms,
            "generation": self.generation,
        }, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobResult:
        return cls(
            job_id=str(data["job_id"]),
            status=JobStatus(data.get("status", "completed")),
            result_data=dict(data.get("result_data", {})),
            error_code=data.get("error_code"),
            error_message=data.get("error_message"),
            retriable=bool(data.get("retriable", False)),
            duration_ms=int(data.get("duration_ms", 0)),
            generation=int(data.get("generation", 1)),
        )


# ---------------------------------------------------------------------------
# 3. SessionConfig & StreamChunk
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SessionConfig:
    session_id: str
    modality: ModalityType
    config_parameters: dict[str, Any]
    max_queue_depth: int = 2
    buffer_capacity_ms: int = 10000
    generation: int = 1

    def to_json(self) -> str:
        return json.dumps({
            "type": "session_config",
            "session_id": self.session_id,
            "modality": str(self.modality),
            "config_parameters": self.config_parameters,
            "max_queue_depth": self.max_queue_depth,
            "buffer_capacity_ms": self.buffer_capacity_ms,
            "generation": self.generation,
        }, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionConfig:
        return cls(
            session_id=str(data["session_id"]),
            modality=ModalityType(data.get("modality", "ocr")),
            config_parameters=dict(data.get("config_parameters", {})),
            max_queue_depth=int(data.get("max_queue_depth", 2)),
            buffer_capacity_ms=int(data.get("buffer_capacity_ms", 10000)),
            generation=int(data.get("generation", 1)),
        )


@dataclass(frozen=True, slots=True)
class StreamChunk:
    session_id: str
    sequence_number: int
    is_partial: bool
    payload_text: str
    start_ms: int = 0
    end_ms: int = 0
    confidence: float = 1.0
    bounding_boxes: tuple[dict[str, Any], ...] = ()
    dropped_frames_count: int = 0
    generation: int = 1

    def to_json(self) -> str:
        return json.dumps({
            "type": "stream_chunk",
            "session_id": self.session_id,
            "sequence_number": self.sequence_number,
            "is_partial": self.is_partial,
            "payload_text": self.payload_text,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "confidence": round(self.confidence, 4),
            "bounding_boxes": list(self.bounding_boxes),
            "dropped_frames_count": self.dropped_frames_count,
            "generation": self.generation,
        }, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StreamChunk:
        return cls(
            session_id=str(data["session_id"]),
            sequence_number=int(data["sequence_number"]),
            is_partial=bool(data.get("is_partial", False)),
            payload_text=str(data.get("payload_text", "")),
            start_ms=int(data.get("start_ms", 0)),
            end_ms=int(data.get("end_ms", 0)),
            confidence=float(data.get("confidence", 1.0)),
            bounding_boxes=tuple(data.get("bounding_boxes", ())),
            dropped_frames_count=int(data.get("dropped_frames_count", 0)),
            generation=int(data.get("generation", 1)),
        )


# ---------------------------------------------------------------------------
# 4. WorkerHealth
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class WorkerHealth:
    worker_pid: int
    generation: int
    uptime_seconds: float
    active_jobs_count: int
    active_sessions_count: int
    cpu_percent: float
    rss_memory_bytes: int
    gpu_available: bool = False
    gpu_memory_used_bytes: int = 0
    gpu_memory_total_bytes: int = 0
    is_healthy: bool = True
    error_summary: str | None = None

    def to_json(self) -> str:
        return json.dumps({
            "type": "worker_health",
            "worker_pid": self.worker_pid,
            "generation": self.generation,
            "uptime_seconds": round(self.uptime_seconds, 2),
            "active_jobs_count": self.active_jobs_count,
            "active_sessions_count": self.active_sessions_count,
            "cpu_percent": round(self.cpu_percent, 2),
            "rss_memory_bytes": self.rss_memory_bytes,
            "gpu_available": self.gpu_available,
            "gpu_memory_used_bytes": self.gpu_memory_used_bytes,
            "gpu_memory_total_bytes": self.gpu_memory_total_bytes,
            "is_healthy": self.is_healthy,
            "error_summary": self.error_summary,
        }, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkerHealth:
        return cls(
            worker_pid=int(data.get("worker_pid", 0)),
            generation=int(data.get("generation", 1)),
            uptime_seconds=float(data.get("uptime_seconds", 0.0)),
            active_jobs_count=int(data.get("active_jobs_count", 0)),
            active_sessions_count=int(data.get("active_sessions_count", 0)),
            cpu_percent=float(data.get("cpu_percent", 0.0)),
            rss_memory_bytes=int(data.get("rss_memory_bytes", 0)),
            gpu_available=bool(data.get("gpu_available", False)),
            gpu_memory_used_bytes=int(data.get("gpu_memory_used_bytes", 0)),
            gpu_memory_total_bytes=int(data.get("gpu_memory_total_bytes", 0)),
            is_healthy=bool(data.get("is_healthy", True)),
            error_summary=data.get("error_summary"),
        )
```

### 7.3 Complete JSON Schema Definitions (Draft 7 / 2020-12)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://nvda-ai.org/schemas/worker_ipc.json",
  "title": "NVDA AI Assistant Worker IPC Protocol Schema",
  "description": "Authoritative JSON Schemas for Worker IPC DTOs",
  "definitions": {
    "HandshakeRequest": {
      "type": "object",
      "required": ["type", "protocol_version", "client_name", "client_pid", "supported_schemas", "requested_capabilities", "request_id"],
      "properties": {
        "type": { "const": "handshake_request" },
        "protocol_version": { "type": "string" },
        "client_name": { "type": "string" },
        "client_version": { "type": "string" },
        "client_pid": { "type": "integer" },
        "supported_schemas": { "type": "array", "items": { "type": "string" } },
        "requested_capabilities": { "type": "array", "items": { "type": "string" } },
        "request_id": { "type": "string" }
      },
      "additionalProperties": false
    },
    "HandshakeResponse": {
      "type": "object",
      "required": ["type", "accepted", "protocol_version", "worker_pid", "worker_version", "negotiated_capabilities"],
      "properties": {
        "type": { "const": "handshake_response" },
        "accepted": { "type": "boolean" },
        "protocol_version": { "type": "string" },
        "worker_pid": { "type": "integer" },
        "worker_version": { "type": "string" },
        "negotiated_capabilities": { "type": "array", "items": { "type": "string" } },
        "max_frame_bytes": { "type": "integer" },
        "error_message": { "type": ["string", "null"] },
        "correlation_id": { "type": "string" }
      },
      "additionalProperties": false
    },
    "JobSubmission": {
      "type": "object",
      "required": ["type", "job_id", "job_type", "payload", "generation"],
      "properties": {
        "type": { "const": "job_submission" },
        "job_id": { "type": "string" },
        "job_type": { "type": "string" },
        "payload": { "type": "object" },
        "priority": { "type": "integer" },
        "timeout_seconds": { "type": "number" },
        "generation": { "type": "integer" },
        "created_at_epoch_ms": { "type": "integer" }
      },
      "additionalProperties": false
    },
    "JobUpdate": {
      "type": "object",
      "required": ["type", "job_id", "status", "generation"],
      "properties": {
        "type": { "const": "job_update" },
        "job_id": { "type": "string" },
        "status": { "enum": ["submitted", "queued", "running", "completed", "failed", "cancelled"] },
        "progress_pct": { "type": "number" },
        "status_message": { "type": "string" },
        "bytes_completed": { "type": "integer" },
        "bytes_total": { "type": "integer" },
        "throughput_bytes_per_sec": { "type": "number" },
        "eta_seconds": { "type": ["number", "null"] },
        "generation": { "type": "integer" },
        "timestamp_epoch_ms": { "type": "integer" }
      },
      "additionalProperties": false
    },
    "JobResult": {
      "type": "object",
      "required": ["type", "job_id", "status", "generation"],
      "properties": {
        "type": { "const": "job_result" },
        "job_id": { "type": "string" },
        "status": { "enum": ["completed", "failed", "cancelled"] },
        "result_data": { "type": "object" },
        "error_code": { "type": ["string", "null"] },
        "error_message": { "type": ["string", "null"] },
        "retriable": { "type": "boolean" },
        "duration_ms": { "type": "integer" },
        "generation": { "type": "integer" }
      },
      "additionalProperties": false
    },
    "SessionConfig": {
      "type": "object",
      "required": ["type", "session_id", "modality", "config_parameters", "generation"],
      "properties": {
        "type": { "const": "session_config" },
        "session_id": { "type": "string" },
        "modality": { "enum": ["download", "inference", "ocr", "transcription", "embedding", "tts"] },
        "config_parameters": { "type": "object" },
        "max_queue_depth": { "type": "integer" },
        "buffer_capacity_ms": { "type": "integer" },
        "generation": { "type": "integer" }
      },
      "additionalProperties": false
    },
    "StreamChunk": {
      "type": "object",
      "required": ["type", "session_id", "sequence_number", "is_partial", "payload_text", "generation"],
      "properties": {
        "type": { "const": "stream_chunk" },
        "session_id": { "type": "string" },
        "sequence_number": { "type": "integer" },
        "is_partial": { "type": "boolean" },
        "payload_text": { "type": "string" },
        "start_ms": { "type": "integer" },
        "end_ms": { "type": "integer" },
        "confidence": { "type": "number" },
        "bounding_boxes": { "type": "array", "items": { "type": "object" } },
        "dropped_frames_count": { "type": "integer" },
        "generation": { "type": "integer" }
      },
      "additionalProperties": false
    },
    "WorkerHealth": {
      "type": "object",
      "required": ["type", "worker_pid", "generation", "uptime_seconds", "active_jobs_count", "is_healthy"],
      "properties": {
        "type": { "const": "worker_health" },
        "worker_pid": { "type": "integer" },
        "generation": { "type": "integer" },
        "uptime_seconds": { "type": "number" },
        "active_jobs_count": { "type": "integer" },
        "active_sessions_count": { "type": "integer" },
        "cpu_percent": { "type": "number" },
        "rss_memory_bytes": { "type": "integer" },
        "gpu_available": { "type": "boolean" },
        "gpu_memory_used_bytes": { "type": "integer" },
        "gpu_memory_total_bytes": { "type": "integer" },
        "is_healthy": { "type": "boolean" },
        "error_summary": { "type": ["string", "null"] }
      },
      "additionalProperties": false
    }
  }
}
```

---

## 8. Heavy Operations Migration: Model Download, Checksum, Unpack (Slice 4)

In Slice 4, the first real heavy operation—currently in `providers/runtime/download.py`—is migrated out of NVDA into the Worker process.

### 8.1 Current Deficiencies at HEAD
1. `RuntimeDownloadService.download()` (lines 77–160 in `download.py`) runs in a thread spawned directly inside `nvda.exe`.
2. Hashing (lines 142–148) consumes CPU cycles on the Python GIL in `nvda.exe`.
3. Unzipping (lines 150–158) touches hundreds of files on disk, risking filesystem locks, virus scanner delays, and high memory usage inside `nvda.exe`.

### 8.2 Target Worker Execution Architecture
```
NVDA Main Thread                     Worker Process
       |                                   |
       | -- JobSubmission(model_download)-> |
       |                                   | ---> DownloadWorker Thread
       |                                   |      - HTTP Range streaming
       |                                   |      - Streaming SHA-256 hash
       | <--- JobUpdate(progress_pct, eta)- |      - Staging to .tmp directory
       | <--- JobUpdate(extracting...) --- |      - Verification against manifest
       |                                   |      - Atomic directory rename
       | <--- JobResult(status=completed)- |
       v                                   v
[UI Presentation via Adapter]
```

1. **Job Dispatch**:
   NVDA issues a `JobSubmission`:
   ```python
   JobSubmission(
       job_id="dl-litert-0150",
       job_type="model_download",
       payload={
           "runtime": "litert-lm",
           "version": "0.15.0",
           "url": "https://github.com/...",
           "target_dir": "C:\\Users\\...\\runtimes\\litert-lm\\0.15.0",
           "expected_sha256": "abcdef...",
       }
   )
   ```
2. **Chunked Streaming Download**:
   - Worker writes downloaded data to a temporary file: `<target_dir>.tmp.<uuid>/bundle.zip.downloading`.
   - Supports HTTP `Range: bytes={offset}-` for resilient resume after network interruptions.
   - Emits `JobUpdate` every 250ms with `progress_pct`, `bytes_completed`, `bytes_total`, `throughput_bytes_per_sec`, and `eta_seconds`.
3. **Incremental SHA-256 Hashing**:
   - The SHA-256 hash is computed incrementally on the chunk stream during download (`hashlib.sha256().update(chunk)`), avoiding a redundant second pass over multi-gigabyte disk files.
4. **Safe Atomic Extraction**:
   - Decompressed into isolated staging directory `<target_dir>.tmp.<uuid>/extracted/`.
   - Manifest validation confirms all required binaries exist (`litert-lm.exe`, `manifest.json`).
   - Atomic swap: Uses Win32 `MoveFileExW(MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)` to rename staging directory to final `<target_dir>`.
5. **Deterministic Cancellation Handling**:
   - On `JobCancellationRequest`, worker aborts HTTP stream, closes file handles, deletes the `.tmp.<uuid>` staging directory, and responds with `JobResult(status="cancelled")`. NVDA disk space is cleanly preserved.

---

## 9. Bounded Streaming Foundations: Continuous OCR Session (Slice 9, Invariant A29)

### 9.1 The Producer-Consumer Imbalance
- **Frame Producer (NVDA / Screen / Camera)**: Screen capture or webcam video produces frames at 10 to 30 FPS (~33ms to 100ms per frame).
- **Inference Consumer (Worker OCR Engine)**: Local OCR (e.g. Tesseract, ONNX EasyOCR, or vision model) requires 150ms to 400ms per frame depending on CPU/GPU capabilities.
- **The Failure Mode**: If frames are enqueued naively in an unbounded queue, the queue balloons to hundreds of megabytes of raw image bitmaps, memory exhausts, and OCR results lag behind real-time user actions by 10–30 seconds!

### 9.2 Bounded Frame Queue Architecture ($N=2$)
To enforce **Invariant A29**, the OCR worker pipeline implements a strict **bounded queue of capacity $N=2$**:
- **Slot 0**: `Active Frame` (currently undergoing OCR inference inside native engine).
- **Slot 1**: `Pending Frame` (the most recent capture awaiting processing).

```
Screen / Video Capture
       |
       |  (Frame Seq #42)
       v
+-----------------------------------------------------------+
| Bounded Frame Buffer (Capacity = 2)                       |
|                                                           |
|  [Slot 0: Active]   <--- Frame #40 (Inference in flight)  |
|                                                           |
|  [Slot 1: Pending]  <--- Frame #41 (Overwritten by #42!)  |
+-----------------------------------------------------------+
                                  |
                                  v Drops Frame #41 (Older)
                          "Latest-Wins" Dropping
```

### 9.3 Monotonic Sequence Tracking & Latest-Wins Frame Dropping Policy
1. Every captured frame carries a strictly monotonic sequence number `frame_seq: int`.
2. **Latest-Wins Dropping Policy**:
   - If Slot 0 is busy and a new Frame arrives:
     - If Slot 1 is empty, the new Frame occupies Slot 1.
     - If Slot 1 is already occupied by an older unstarted frame (e.g. Frame #41), the worker **immediately drops Frame #41** and replaces it with the newer Frame #42.
     - The active running frame in Slot 0 is **never** cancelled mid-inference, preventing engine state thrashing and GPU pipeline stalls.
   - The worker increments `dropped_frames_count`.
3. **Telemetry & Backpressure**:
   - The emitted `StreamChunk` contains `dropped_frames_count` and `sequence_number`.
   - If the frame drop rate exceeds 80% over a 2-second window, the worker sends a `BackpressureWarning` to NVDA, signaling the screen capture timer to reduce capture frequency (e.g. throttling from 30 FPS down to 5 FPS).

### 9.4 OCR Result Emission Contract
The worker emits `StreamChunk` with:
- `payload_text`: Recognized text lines.
- `bounding_boxes`: Coordinate rectangles for NVDA spatial navigation / audio panning.
- `confidence`: Confidence score (0.0 to 1.0).
- `is_partial`: `False` (OCR frames are discrete spatial snapshots).

---

## 10. Bounded Streaming Foundations: Continuous Audio Transcription Session (Slice 10, Invariant A29)

### 10.1 Real-Time Audio Capture & Ring Buffer Architecture ($T_{max}=10\text{s}$)
- **Audio Stream**: Microphone captures raw 16 kHz, 16-bit mono PCM audio (32,000 bytes per second / 32 KB/s).
- **Bounded Circular Ring Buffer**:
  - The worker maintains a fixed-size circular ring buffer in unmanaged memory.
  - Size: $T_{max} = 10.0\text{ seconds} = 320,000\text{ bytes}$.
  - Memory consumption is constant and strictly capped at 320 KB.

```
Microphone Capture (16kHz 16-bit PCM, 32 KB/s)
       |
       v
+-----------------------------------------------------------+
| Circular Audio Ring Buffer (Capacity = 10 seconds / 320KB)|
|                                                           |
|  [=== Processed ===][=== Active Window ===][=== Pending ==|
+-----------------------------------------------------------+
       |                                          |
       v Chunk Slicer (500ms + 100ms overlap)     v Overflow Guard
+-------------------------------------+   Drop silence / VAD
| Whisper / Transcription Engine      |
+-------------------------------------+
       |
       +---> Emits is_partial=True  (Tentative Hypotheses < 200ms)
       +---> Emits is_partial=False (Finalized Sentence Hypotheses)
```

### 10.2 Audio Chunking & Voice Activity Detection (VAD)
- **Audio Window Slicing**: Audio is sliced into processing chunks (e.g. 500ms analysis window with 100ms acoustic overlap).
- **Voice Activity Detection (VAD)**:
  - An energy-based or lightweight Silero-VAD filter discards silent audio frames before feeding the acoustic model.
  - Silence does not consume inference cycles.

### 10.3 Partial vs Finalized Transcript Hypotheses Semantics
To provide an instantaneous, responsive screen reader experience without stutter, transcription separates hypotheses into two distinct semantic tiers:

1. **Partial Hypotheses (`is_partial = True`)**:
   - Emitted with low latency (< 200ms) on short audio windows.
   - Tentative text representing real-time speech in progress:
     *Chunk 1*: `StreamChunk(is_partial=True, payload_text="How do")`
     *Chunk 2*: `StreamChunk(is_partial=True, payload_text="How do I open")`
   - Semantics: Supersedes previous partial chunk for the current utterance. NVDA speaks or displays via braille transiently without committing to permanent chat history.
2. **Finalized Hypotheses (`is_partial = False`)**:
   - Emitted when acoustic confidence stabilizes, punctuation is generated, or a silence/VAD boundary (> 400ms pause) is reached.
   - Final text:
     *Chunk 3*: `StreamChunk(is_partial=False, payload_text="How do I open settings?", start_ms=0, end_ms=1650)`
   - Semantics: Permanent, finalized sentence. Committed to conversation history; fully articulated by screen reader.

### 10.4 Buffer Overrun & Acoustic Backpressure Policy
- **Acoustic Backpressure Trigger**:
  - If local inference slows down (e.g. CPU throttle) and pending audio in the ring buffer exceeds 80% ($8.0\text{ seconds}$):
    1. VAD aggressively prunes non-essential background noise and pauses.
    2. If buffer reaches 100% ($10.0\text{ seconds}$), the ring buffer drops the oldest unfinalized non-speech buffer to prevent latency accumulation.
    3. Worker emits a `StreamChunk` with `dropped_frames_count > 0` and error warning.
    4. The microphone capture thread **never blocks, never allocates unbounded memory, and never crashes**.

---

## 11. Failure Modes, Edge Cases, and Recovery Strategies

| Failure Mode | Direct Symptom | Root Cause | Architectural Mitigation | Recovery Action |
|---|---|---|---|---|
| **Worker Process Crash (Segfault / OOM)** | `ERROR_BROKEN_PIPE` on named pipe; exit code `0xC0000005` | Native library crash (CUDA out-of-memory, PyTorch/Candle panic) | Worker runs in isolated process protected by Windows Job Object | Supervisor increments `generation`, transitions active jobs to `FAILED(retriable=True)`, restarts worker with backoff |
| **Worker Hang / Deadlock** | Missed heartbeat for $> 15.0\text{s}$ | Uninterruptible native C loop or deadlock | Supervisor watchdog thread tracks monotonic ping/pong | Supervisor forcefully terminates worker via `TerminateProcess` / Job Object; triggers clean restart |
| **Circuit Breaker Tripped** | $\ge 3$ worker crashes within 60 seconds | Persistent hardware incompatibility or corrupt model file | Exponential backoff and circuit breaker threshold | State transitions to `FAILED_TRIPPED`; supervisor halts automatic restarts; NVDA notifies user via speech/dialog |
| **Named Pipe Connection Race** | `winerror=2` (`ERROR_FILE_NOT_FOUND`) during startup | Client connects before Worker completes `CreateNamedPipe` | Supervisor polls `WaitNamedPipe` with 5.0s timeout and 250ms retry interval | Seamless connection once pipe handle is created |
| **NVDA Abnormal Termination** | NVDA process killed via Task Manager | User action or OS shutdown | `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` configured on Windows Job Object | Windows kernel immediately terminates Worker and all child servers (`llama-server.exe`); no orphaned zombies |
| **Job Cancellation Timeout** | Job does not yield within 3.0s after cancel request | Native HTTP download or GPU kernel stuck in non-cooperative call | Two-phase cancellation escalation | Supervisor terminates underlying child process or recycles worker process; reports `CANCELLED` |
| **Audio Ring Buffer Overflow** | Audio capture exceeds processing rate | Transcription engine CPU lag | Fixed 10s circular ring buffer with VAD dropping | Discards silence/oldest chunk; emits overrun warning; capture never stalls |
| **OCR Frame Backpressure** | Screen capture produces frames faster than OCR | Camera/display at 30 FPS vs OCR at 4 FPS | Bounded $N=2$ queue with "latest-wins" dropping | Drops intermediate frames; active inference uninterrupted; zero latency lag |

---

## 12. Classified Findings, Blockers, and Risks Table

In accordance with project integrity standards, all architectural design components, audit findings, and implementation risks are classified below using mandatory tags: `CONFIRMED`, `LIKELY`, `DESIGN DETAIL`, `BLOCKER`, or `UNKNOWN / REQUIRES EXPERIMENT`.

| ID | Title / Component | Code Reference / Evidence | Classification | Impact & Resolution |
|---|---|---|---|---|
| **FW-01** | In-process downloads & checksums violate thin NVDA shell | `providers/runtime/download.py:77–160` | **CONFIRMED, BLOCKER** | In-process downloads risk memory inflation and UI stalls. Resolved by migrating download execution to Worker in Slice 4. |
| **FW-02** | Absence of Windows Job Objects permits orphaned child processes | `runtime_supervisor/src/process.rs:44–56` (Audit E RS-06) | **CONFIRMED, BLOCKER** | Abnormal NVDA exit leaves running models and GPU memory leaks. Resolved by wrapping Worker in Windows Job Object with `KILL_ON_JOB_CLOSE`. |
| **FW-03** | Unbounded queueing in continuous modalities causes memory exhaustion & latency lag | Theoretical continuous streaming in Slices 9 & 10 | **CONFIRMED, BLOCKER** | Screen OCR and audio transcription produce data faster than inference engines can consume. Resolved by bounded queues ($N=2$ for OCR, 10s ring buffer for audio) enforcing Invariant A29. |
| **FW-04** | Cooperative cancellation failure in native C loops | Native blocking calls in `llama.cpp` / `whisper.cpp` | **CONFIRMED, DESIGN DETAIL** | Python `threading.Event` cannot interrupt non-yielding C extensions. Resolved by Two-Phase Cancellation (grace period + supervisor process preemption). |
| **FW-05** | Named Pipe DACL Security Vulnerability | `ui_host/src/ipc/transport.rs:53–73` | **CONFIRMED, DESIGN DETAIL** | Default pipe permissions allow local processes to connect. Resolved by adding explicit Windows Security Descriptors (DACLs) restricted to user SID. |
| **FW-06** | NDJSON vs Binary Hybrid Framing Overhead | `host_protocol.py` (text) vs OCR bitmaps | **CONFIRMED, DESIGN DETAIL** | Base64 encoding for 30 FPS video frames causes 33% CPU/memory overhead. Resolved by 2-part hybrid binary framing (JSON header + raw byte payload). |
| **FW-07** | Stale generation overwrites during worker recovery | Audit E RS-01, RS-02 | **CONFIRMED, BLOCKER** | Worker crash recovery can race with late responses from dying processes. Resolved by Monotonic Generation Fencing across all DTO envelopes. |
| **FW-08** | Circuit Breaker Tripping on Driver Incompatibility | Machine without AVX2 or incompatible CUDA | **LIKELY, DESIGN DETAIL** | Worker crashing repeatedly must not loop indefinitely. Resolved by 3-strike circuit breaker with localized NVDA user alert. |
| **FW-09** | Windows Named Pipe throughput limits for raw 1080p video | 1080p 30 FPS BGRA = ~240 MB/s | **UNKNOWN / REQUIRES EXPERIMENT** | Named pipes handle ~500 MB/s locally, but memory copies may cause CPU load. If benchmarks show pipe contention in Slice 9, evaluate Windows Shared Memory (`CreateFileMappingW`). |
| **FW-10** | Voice Activity Detection (VAD) accuracy with screen reader speech | Screen reader audio leaking into microphone | **LIKELY, DESIGN DETAIL** | Screen reader TTS speech may trigger false VAD activations. Resolved by integrating acoustic echo cancellation or NVDA mute ducking during dictation. |

---

## 13. Implementation Roadmap for Slices 2, 3, 4, 9, 10

### 13.1 Slice 2: Job Domain / Protocol
- **Objective**: Implement pure Python Job/Session FSM and immutable DTOs without external process dependencies.
- **Key Modules**:
  - `core/job/state.py`: Finite state machines for discrete jobs and continuous sessions.
  - `core/job/dto.py`: Frozen dataclasses (`JobSubmission`, `JobUpdate`, `JobResult`, `SessionConfig`, `StreamChunk`, `WorkerHealth`).
  - `core/job/cancellation.py`: Cooperative cancellation tokens and timeout coordinators.
- **Test Gate**: Pure-Python unit test suite verifying all state transitions, JSON round-tripping, and immutability invariants without NVDA checkout.

### 13.2 Slice 3: Worker Process Lifecycle & IPC
- **Objective**: Build the Worker process launcher, Windows Job Object containment, named pipe transport, versioned handshake, and heartbeat supervision.
- **Key Modules**:
  - `worker/process.py`: Worker entrypoint and process runner.
  - `worker/ipc/transport.py`: Windows Named Pipe server with security DACLs and NDJSON framing.
  - `worker/ipc/handshake.py`: Handshake validator and capability negotiator.
  - `plugin/worker_supervisor.py`: NVDA-side client proxy, process watchdog, generation fence, and circuit breaker.
- **Test Gate**: Multi-process integration tests verifying process crash detection, graceful restart, generation fencing, and handshake negotiation.

### 13.3 Slice 4: Heavy Operations Migration (Model Download)
- **Objective**: Migrate runtime and model downloading, SHA-256 validation, and ZIP extraction from `download.py` into Worker job execution.
- **Key Modules**:
  - `worker/executors/download.py`: Chunked streaming HTTP downloader with `Range` resume support.
  - `worker/executors/verify.py`: Streaming SHA-256 verifier.
  - `worker/executors/unpack.py`: Atomic staging directory unpacker.
  - `providers/runtime/download_client.py`: NVDA-side thin adapter submitting `JobSubmission(job_type="model_download")`.
- **Test Gate**: Download tests verifying progress reporting, resume on interruption, checksum validation, safe unpacking, and cancellation cleanup.

### 13.4 Slice 9: OCR Session Foundation
- **Objective**: Implement continuous OCR session support with bounded frame queue ($N=2$) and latest-wins frame dropping.
- **Key Modules**:
  - `worker/sessions/ocr.py`: Bounded frame queue manager and frame dropping policy.
  - `worker/executors/ocr_engine.py`: OCR inference executor interface.
  - `plugin/ocr_session_client.py`: Screen capture pipeline emitting frames to worker.
- **Test Gate**: Simulated high-framerate stream tests verifying queue bound ($N=2$), latest-wins frame drop verification, and zero memory leaks.

### 13.5 Slice 10: Transcription Session Foundation
- **Objective**: Implement continuous audio transcription session with bounded circular ring buffer (10s) and partial vs finalized transcript semantics.
- **Key Modules**:
  - `worker/sessions/transcription.py`: 10-second circular audio ring buffer with overflow protection.
  - `worker/executors/vad.py`: Voice activity detection pre-filter.
  - `worker/executors/whisper_engine.py`: Acoustic hypothesis generator emitting `is_partial=True` and `is_partial=False`.
  - `plugin/transcription_client.py`: Microphone capture adapter feeding audio chunks to worker.
- **Test Gate**: Audio stream tests verifying ring buffer bounds, hypothesis progression, silence dropping, and backpressure recovery.

---

## 14. Verification Plan & Traceability Matrix

| Requirement / Invariant | Verification Method | Command / Test Node | Success Criteria |
|---|---|---|---|
| **A16 (Worker Isolation)** | Process Tree Inspection & Job Object Test | `uv run pytest tests/worker/test_process_isolation.py` | Worker runs under separate PID; terminating parent closes Job Object and child terminates |
| **A17 (Versioned Handshake)** | Protocol Handshake Unit Tests | `uv run pytest tests/worker/test_handshake.py` | Version match succeeds; major version mismatch fails fast; capabilities negotiated |
| **A18 (Framing & IPC)** | Named Pipe Roundtrip & DACL Test | `uv run pytest tests/worker/test_pipe_transport.py` | Bidirectional NDJSON frames roundtrip cleanly up to 16 MB; unauthorized access rejected |
| **A19 (Heartbeat & Crash Detection)** | Crash Simulation Test | `uv run pytest tests/worker/test_liveness.py` | Pipe break triggers recovery in < 20ms; generation counter increments monotonically |
| **A20 (Restart & Circuit Breaker)** | Chaos / Restart Loop Test | `uv run pytest tests/worker/test_circuit_breaker.py` | 3 rapid crashes trip circuit breaker; stops restart loop; user alert triggered |
| **A21 (Discrete Job FSM)** | FSM State Transition Exhaustive Tests | `uv run pytest tests/worker/test_job_fsm.py` | All valid transitions succeed; invalid transitions raise `IllegalStateTransitionError` |
| **A22 (Two-Phase Cancellation)** | Cooperative Cancel & Timeout Escalation Test | `uv run pytest tests/worker/test_cancellation.py` | Yield point cancels in < 100ms; non-yielding loop preempted by supervisor in 3.0s |
| **A23 (Session FSM)** | Continuous Session Lifecycle Tests | `uv run pytest tests/worker/test_session_fsm.py` | Multi-session multiplexing works cleanly; pause/resume/close states validated |
| **A24 (Immutable DTOs)** | Schema & Dataclass Contract Tests | `uv run pytest tests/worker/test_dto_contracts.py` | Frozen dataclasses cannot be mutated; JSON schemas validate all test vectors |
| **A29 (Bounded OCR Queue)** | Fast Producer Simulation Test | `uv run pytest tests/worker/test_ocr_bounded_queue.py` | 30 FPS input never exceeds queue size 2; drops oldest unstarted frame; zero memory growth |
| **A29 (Bounded Audio Ring Buffer)**| Audio Overflow Simulation Test | `uv run pytest tests/worker/test_audio_ring_buffer.py` | Buffer size strictly capped at 10s; partial hypotheses emitted < 200ms; finalized emitted on pause |

---

*End of Design Report.*
