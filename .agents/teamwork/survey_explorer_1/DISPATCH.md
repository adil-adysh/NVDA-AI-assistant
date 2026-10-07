## 2026-10-05T01:56:11Z
Your working directory is: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\survey_explorer_1
Your parent is: orchestrator_slice2_3 (conversation ID: a7e13a13-3301-4ca2-8072-eb893a10b4b4)

MANDATORY INPUTS:
- Read ORIGINAL_REQUEST.md at D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\ORIGINAL_REQUEST.md (specifically timestamp 2026-10-05T01:52:03Z and lines 151-210)
- Read architecture_deliverable.md at D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\architecture_deliverable.md (specifically sections 14, 15, 16, 17 Slice 2, 18 Slice 2, Invariants A17, A18, A20, A21, A22, A24)

OBJECTIVE:
Perform a comprehensive survey and specification extraction for Migration Slice 2: Job Domain, State Machines, and Versioned IPC Protocol.

INVESTIGATION SCOPE:
1. Immutable Job DTOs:
   - Identify exact specifications for:
     a) Frozen dataclasses with slots (JobId, JobSpec, JobSnapshot, JobProgress, JobResult, JobFailure, JobState per prompt R1)
     b) Wire DTOs per Section 16 (HandshakeRequest, HandshakeResponse, JobSubmission, JobUpdate, JobResult, SessionConfig, StreamChunk, WorkerHealth, JobStatus, SessionState, ModalityType)
   - How should they be organized in addon/globalPlugins/AI-assistant/core/job/ or core/job/? (Check imports and packaging)
   - Serialization / Deserialization: JSON / NDJSON encoding/decoding, datetime / epoch ms handling, Draft 2020-12 schema validation.
2. Job Finite State Machine (FSM):
   - Strict monotonic discrete FSM: SUBMITTED -> QUEUED -> RUNNING -> terminal COMPLETED / FAILED / CANCELLED.
   - Validation of illegal state regressions and transitions.
   - Session State Machine (INIT, CONFIGURING, READY, STREAMING, PAUSED, CLOSING, CLOSED, ERROR).
3. Cancellation Contract:
   - Two-phase cancellation model: cooperative yield token (CancellationToken) + supervisor preemption timeout.
   - Fine-grained yield points.
4. Versioned Wire Protocol:
   - v1.0.0 semantic handshake, frame envelope, typed error codes, JSON/NDJSON framing.
5. Pure-Python Client Interfaces:
   - WorkerClient and JobClient abstract base classes (ABC) and mock implementations for isolated testing.
6. Acceptance & Test Requirements:
   - Pure-Python tests under tests/ verifying DTO immutability, round-trip serialization, FSM transitions, and cancellation.

OUTPUT:
Write your complete survey report to:
D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\survey_explorer_1\handoff.md
Send a summary message back to parent when complete.
