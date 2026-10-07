## 2026-10-02T22:40:13Z
You are the Worker / Job / IPC Implementation Designer (Agent 6).
Working Directory: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\design_worker_ipc_1
Parent Conversation ID: 9e3c7398-1a1a-4933-bc73-5d9f0a8d166f
Original Request: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\ORIGINAL_REQUEST.md
Repository Root: D:\nvda-addons\NVDA-AI-assistant

Your mission is to design the Worker Process, Job/Session State Model, and Versioned IPC Architecture enforcing Invariants A16–A24, Invariant A29, and foundational designs for Slices 2–4, 9–10.

Background & Completed Audits to review:
- Audit E (Rust Runtime): `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\audit_rust_runtime_1\audit_report.md`
- Audit D (Pure-Python & Test): `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\audit_pure_python_test_1\audit_report.md`
- Audit F (Model Management): `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\audit_model_management_1\audit_report.md`

Tasks:
1. Worker Process Lifecycle & IPC Design (Invariants A16–A20, Slices 2 & 3):
   - Worker creation, supervision, heartbeat/liveness, crash detection, graceful restart, and isolation from NVDA.
   - Versioned handshake and capability negotiation (major/minor compatibility, protocol schema negotiation).
   - Framing, serialization (JSON / msgpack / NDJSON), bi-directional named pipe / stdio transport, backpressure.

2. Job & Session State Machine (Invariants A21–A24, Slice 2):
   - Finite state machines for discrete jobs (QUEUED -> RUNNING -> COMPLETED / FAILED / CANCELLED).
   - Job cancellation semantics (deterministic cooperative cancellation tokens vs hard worker kill).
   - Session lifecycle for continuous workloads: open, configure, stream, pause, close.

3. Immutable DTO Definitions:
   - Provide complete, typed, immutable Python/JSON schemas:
     `HandshakeRequest`, `HandshakeResponse`, `JobSubmission`, `JobUpdate`, `JobResult`, `SessionConfig`, `StreamChunk`, `WorkerHealth`.

4. Heavy Operations Migration (Slice 4):
   - Design how heavy operations (e.g., model downloading, checksum verification, unpacking) execute in the worker.

5. Bounded Streaming Foundations for Continuous Modalities (Slices 9 & 10, Invariant A29):
   - Slice 9 (OCR Session): Bounded frame queue, monotonic sequence tracking, backpressure policy, intelligent frame dropping when worker is busy.
   - Slice 10 (Transcription Session): Bounded audio ring buffer, chunking, partial vs finalized transcript semantics, backpressure policy.

Requirements:
- Read `ORIGINAL_REQUEST.md` before starting.
- Classify design components and risks with standard tags: CONFIRMED, LIKELY, DESIGN DETAIL, BLOCKER, UNKNOWN / REQUIRES EXPERIMENT.
- Write your complete design deliverable to `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\design_worker_ipc_1\design_report.md`.
- Write your handoff report to `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\design_worker_ipc_1\handoff.md`.
- Communicate completion back to parent via `send_message` with Recipient `9e3c7398-1a1a-4933-bc73-5d9f0a8d166f`.
