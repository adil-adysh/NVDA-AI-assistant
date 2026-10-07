## 2026-10-05T03:30:43Z
You are Explorer 1 (Slice 2 Survey Specialist) for Migration Slice 2 & Slice 3 of adil-adysh/NVDA-AI-assistant.
Your working directory is: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\explorer_slice2_survey

MANDATORY FIRST STEP:
Read D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\ORIGINAL_REQUEST.md in full. Do not skip or summarize.

INPUTS:
- Authoritative User Request: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\ORIGINAL_REQUEST.md (see timestamp 2026-10-05T01:52:03Z)
- Approved Architecture Deliverable: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\architecture_deliverable.md (Sections 14, 15, 16, 17 Slice 2, Invariants A4, A6, A17, A18, A20, A21, A22, A24)
- Existing code under D:\nvda-addons\NVDA-AI-assistant\addon\globalPlugins\AI-assistant\core\
- Existing AST import boundary tests: D:\nvda-addons\NVDA-AI-assistant\tests\test_import_boundaries.py

TASK:
Conduct an exhaustive technical survey of Migration Slice 2: Job Domain, State Machines, and Versioned IPC Protocol.
1. Map exact DTO definitions, fields, types, and defaults for all required immutable DTOs:
   `JobId`, `JobSpec`, `JobSnapshot`, `JobProgress`, `JobResult`, `JobFailure`, `JobState` (and any related ones from Section 16 such as `JobSubmission`, `JobUpdate`, `HandshakeRequest`, `HandshakeResponse`, `SessionConfig`, `StreamChunk`, `WorkerHealth`).
2. Draft 2020-12 JSON schema validation:
   Define exact JSON schema specifications for each DTO, specifying types, required fields, properties, enums, and `additionalProperties: false`.
   Check how pure-Python schema validation should be implemented without introducing external unpinned dependencies.
3. Job & Session Finite State Machines:
   Document the exact discrete states, valid transitions, monotonic progression rules (SUBMITTED -> QUEUED -> RUNNING -> terminal COMPLETED/FAILED/CANCELLED), transition guard exceptions, and immutability after reaching terminal states.
4. Two-Phase Cancellation Contract (Invariant A22):
   Specify `CancellationToken` cooperative checking (yield points) and supervisor preemption escalation.
5. Versioned Wire Protocol:
   Detail framing envelope, protocol versioning (`v1.0.0`), handshake negotiation, command/response framing, event emission over standard JSON/NDJSON streams, and typed error codes.
6. Client Interfaces:
   Define pure-Python `WorkerClient` and `JobClient` abstract interfaces, method signatures, return types, and mock implementations for isolated testing.
7. Verification & Boundary Requirements:
   Confirm that all Slice 2 modules can live under `addon/globalPlugins/AI-assistant/core/job/` and pass Tier 1 (zero NVDA dependency) tests and AST boundary tests.

OUTPUT:
Write your complete survey report to:
`D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\explorer_slice2_survey\report.md`
Then call `send_message` to recipient `eb8f4e3d-cb67-4981-b12a-2c54cfb91f1d` with your summary.
Do NOT modify production code. This is a read-only investigation.
