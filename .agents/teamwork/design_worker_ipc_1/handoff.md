# Handoff Report: Worker / Job / IPC Implementation Design

- **Author**: Worker / Job / IPC Implementation Designer (Agent 6)
- **Recipient**: Parent Orchestrator (`9e3c7398-1a1a-4933-bc73-5d9f0a8d166f`)
- **Repository**: `adil-adysh/NVDA-AI-assistant`
- **HEAD Commit**: `ced1cbc`
- **Deliverable File**: `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\design_worker_ipc_1\design_report.md`
- **Date**: 2026-10-02
- **Status**: COMPLETE & VERIFIED

---

## 1. Observation

Direct code observations from HEAD (`ced1cbc`):

1. **In-Process Heavy Downloads & Decompression**:
   - `addon/globalPlugins/AI-assistant/providers/runtime/download.py:77–160`: `RuntimeDownloadService.download()` downloads multi-gigabyte ZIP archives directly on an ad-hoc thread within the NVDA process.
   - `addon/globalPlugins/AI-assistant/providers/runtime/download.py:142–158`: Synchronous `hashlib.sha256()` hashing and `zipfile.ZipFile.extractall()` block and consume CPU/memory inside `nvda.exe`.
   - `addon/globalPlugins/AI-assistant/providers/runtime/download.py:27`: Imports `from logHandler import log`, directly contaminating the download layer with NVDA internal logging.

2. **Unmanaged Child Process Spawning from NVDA**:
   - `runtime_supervisor/src/process.rs:44–45`: `cmd.stdout(Stdio::null())` and `cmd.stderr(Stdio::null())` discard all child diagnostics.
   - Audit E Finding **RS-06**: Spawning via `Command::new` without a Windows Job Object permits child process leaks (`litert-lm`, `llama-server`) if NVDA terminates unexpectedly.
   - Audit E Finding **RS-13**: Native `RuntimeSupervisor` runs in-process inside `nvda.exe`, violating process boundary isolation.

3. **Unmanaged Background Threads in NVDA**:
   - `addon/globalPlugins/AI-assistant/plugin/background.py:80–85`: `_on_litert_server_config_changed()` spawns unmanaged thread `litert-restart-on-config-change`.
   - `addon/globalPlugins/AI-assistant/plugin/background.py:105–110`: `_on_llama_server_config_changed()` spawns unmanaged thread `llama-shutdown-on-config-change`.
   - `addon/globalPlugins/AI-assistant/plugin/background.py:441–495`: `run_use_case_in_background()` spawns thread `AIassistant{title}Worker` running synchronous inference and readiness checks.

4. **Existing IPC Pattern in Repository**:
   - `addon/globalPlugins/AI-assistant/ui/host_transport.py:21–22` and `nvda_ui_host/src/ipc/transport.rs:21–22`: Named pipes `\\.\pipe\nvda_ai_assistant_ui_cmd` and `\\.\pipe\nvda_ai_assistant_ui_evt`.
   - `nvda_ui_host/src/ipc/transport.rs:146–160`: Newline-delimited framing (`read_until(b'\n')`) with `MAX_FRAME_BYTES = 4 * 1024 * 1024`.
   - Baseline commands pass cleanly:
     - `uv run pytest tests/ui/test_host_protocol.py` (15 passed in 0.02s)
     - `cargo check --manifest-path nvda_ui_host/Cargo.toml` (passed in 0.22s)
     - `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml` (11 passed in 1.53s)

---

## 2. Logic Chain

1. **Premise 1 (NVDA Stability)**: NVDA's Python main thread is strictly thread-affine to Windows accessibility event loops and speech queues. Any block $>50\text{ms}$ causes speech stutter. Any native C/C++ crash (CUDA driver crash, OOM, segfault) inside `nvda.exe` completely crashes the screen reader, disabling the user's computer access.
2. **Premise 2 (Current Code Contamination)**: Observations 1.1, 1.2, and 1.3 show that heavy downloads, native supervisors, embedding computations, and ad-hoc threads currently run inside `nvda.exe`.
3. **Inference 1 (Worker Process Isolation - Invariant A16)**: All heavy execution, model execution, file downloads, and continuous streaming workloads must move out-of-process into a dedicated Worker process (`nvda_ai_worker.exe` / worker subprocess).
4. **Inference 2 (Windows Job Object Containment)**: Observation 1.2 demonstrates child process leak risk. Assigning the worker to an anonymous Windows Job Object configured with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` ensures that if NVDA terminates or is killed, Windows kernel terminates all child and grandchild processes instantly, guaranteeing zero orphaned processes or leaked GPU VRAM.
5. **Inference 3 (Named Pipe Transport & Framing - Invariants A17, A18)**: Extending the proven named pipe pattern from Observation 1.4 provides high-performance, full-duplex IPC. To prevent local privilege escalation, pipes require explicit Windows Security Descriptors (DACLs). Control messages use NDJSON (16 MB limit), while high-throughput continuous modalities (OCR, PCM audio) use 2-part hybrid binary framing.
6. **Inference 4 (Liveness, Generations & Circuit Breaker - Invariants A19, A20)**: Heartbeat ping/pong ($5.0\text{s}$ interval, $15.0\text{s}$ timeout) paired with immediate `ERROR_BROKEN_PIPE` detection enables $<5\text{ms}$ crash detection. Monotonic generation fencing resolves stale state overwrites (RS-01, RS-02). A 3-strike circuit breaker prevents rapid restart loops.
7. **Inference 5 (Job & Session FSM - Invariants A21–A24)**: Discrete jobs require monotonic transitions (`QUEUED` $\to$ `RUNNING` $\to$ `COMPLETED` / `FAILED` / `CANCELLED`) with two-phase cancellation (cooperative token at yield points + 3.0s supervisor preemption). Continuous sessions require multi-state streams (`INIT` $\to$ `CONFIGURING` $\to$ `READY` $\to$ `STREAMING` $\leftrightarrow$ `PAUSED` $\to$ `CLOSING` $\to$ `CLOSED`). All DTOs are strictly typed frozen dataclasses with complete JSON schemas.
8. **Inference 6 (Bounded Streaming Foundations - Invariant A29)**: Screen capture (10–30 FPS) and microphone audio (32 KB/s) produce data faster than inference engines consume it. To prevent unbounded memory growth and latency lag, OCR enforces a bounded queue of capacity $N=2$ with "latest-wins" dropping; Audio transcription enforces a 10-second circular ring buffer with VAD silence dropping and partial vs finalized transcript hypothesis semantics.

---

## 3. Caveats

1. **Raw 1080p Video Bandwidth**: At 1080p 30 FPS, uncompressed BGRA video requires ~240 MB/s. While Windows Named Pipes handle ~500 MB/s locally, user-space buffer copies may create CPU overhead on low-end machines. If benchmarks in Slice 9 reveal pipe saturation, a zero-copy Windows Shared Memory (`CreateFileMappingW`) fast-path should be implemented for raw video frames.
2. **Microphone Echo Cancellation**: During real-time transcription, TTS output from NVDA speech synthesizers can bleed into the microphone. While VAD drops silence, acoustic echo cancellation or ducking should be considered in Slice 10 implementation.
3. **No Code Written Under `addon/`**: In accordance with the role of Implementation Designer, this deliverable produces the authoritative architecture specification and typed schema contracts in `design_report.md`. Production implementation will occur during Slices 2–4, 9–10.

---

## 4. Conclusion

The comprehensive technical design for the **Worker Process, Job/Session State Model, Versioned IPC Architecture, Heavy Operations Migration, and Bounded Streaming Foundations** is complete, fully specified, and documented in:
`D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\design_worker_ipc_1\design_report.md`.

The design strictly enforces **Invariants A16–A24 and Invariant A29**, directly feeds into the 24-section synthesis deliverable (Sections 14, 15, 16), and provides actionable implementation blueprints for Migration Slices 2, 3, 4, 9, and 10.

---

## 5. Verification Method

To independently verify this design deliverable:

1. **Verify Design Report Completeness**:
   - Inspect `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\design_worker_ipc_1\design_report.md`.
   - Confirm all 14 major sections are present, covering:
     - Worker lifecycle, supervision, and Job Object isolation (Invariants A16, A19, A20, Slice 3)
     - Versioned handshake and capability negotiation (Invariant A17)
     - Named pipe framing, DACL security, and backpressure (Invariant A18)
     - Discrete job FSM and two-phase deterministic cancellation (Invariants A21, A22, Slice 2)
     - Continuous session FSM (Invariant A23, Slice 2)
     - Complete Python `@dataclass(frozen=True)` and JSON schemas for all 8 DTOs: `HandshakeRequest`, `HandshakeResponse`, `JobSubmission`, `JobUpdate`, `JobResult`, `SessionConfig`, `StreamChunk`, `WorkerHealth` (Invariant A24)
     - Heavy operations migration (Slice 4)
     - Bounded OCR queue ($N=2$, latest-wins drop) (Slice 9, Invariant A29)
     - Bounded audio ring buffer (10s, partial/finalized hypotheses) (Slice 10, Invariant A29)
     - Classified findings table with standard tags (FW-01 to FW-10).

2. **Verify Baseline Tooling Passes**:
   ```pwsh
   uv run pytest tests/ui/test_host_protocol.py
   cargo check --manifest-path nvda_ui_host/Cargo.toml
   uv run cargo test --manifest-path runtime_supervisor/Cargo.toml
   uv run ruff check .
   ```

3. **Invalidation Conditions**:
   - The design is invalidated if the worker process is allowed to run in-process within `nvda.exe`.
   - The design is invalidated if continuous streaming queues allow unbounded allocation without drop policies.
   - The design is invalidated if cancellation relies on unsafe thread aborts rather than cooperative yield tokens and supervisor timeouts.
