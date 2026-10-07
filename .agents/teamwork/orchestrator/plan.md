# Plan: Evidence-Driven Architecture Audit & Implementation Plan

## Objective
Produce the authoritative 24-section pre-implementation deliverable (R2) and Slices 0–10 migration plan (R3) backed by code-level evidence from HEAD (`ced1cbc`) across all 7 Audits A–G (R1), enforcing invariants A1–A30.

## Work Streams & Team Allocation
1. **Agent 1: Current Architecture & Dependency Auditor**
   - Type: `teamwork_preview_explorer`
   - Scope: Audit A (Process Topology), Audit C (NVDA Import Contamination), Audit G (`plugin/background.py` Decomposition).
   - Working Directory: `.agents/teamwork/audit_arch_dep_1`

2. **Agent 2: NVDA Boundary & Thread-Affinity Auditor**
   - Type: `teamwork_preview_explorer`
   - Scope: Audit A (Process Topology interactions), Audit B (Thread & Executor Map), Invariants A1–A4, A27.
   - Working Directory: `.agents/teamwork/audit_nvda_thread_1`

3. **Agent 3: Rust Runtime & Concurrency Auditor**
   - Type: `teamwork_preview_explorer`
   - Scope: Audit E (Rust Runtime Supervisor Verification), Invariants A7–A10, A25–A26.
   - Working Directory: `.agents/teamwork/audit_rust_runtime_1`

4. **Agent 4: Pure-Python & Test Architect**
   - Type: `teamwork_preview_explorer`
   - Scope: Audit D (Testing Tier Separation), Invariants A5–A6, A30, baseline verification commands check.
   - Working Directory: `.agents/teamwork/audit_pure_python_test_1`

5. **Agent 5: Model-Management Architect**
   - Type: `teamwork_preview_explorer`
   - Scope: Audit F (Model Management Consolidation), Invariants A11–A15 across all modalities.
   - Working Directory: `.agents/teamwork/audit_model_management_1`

6. **Agent 6: Worker / Job / IPC Implementation Designer**
   - Type: `teamwork_preview_worker`
   - Scope: Worker boundary, versioned IPC, immutable DTOs, job/session state machine, bounded queues, Invariants A16–A24, Slices 2–4, 9–10.
   - Working Directory: `.agents/teamwork/design_worker_ipc_1`

7. **Agent 7: Migration & Regression Reviewer**
   - Type: `teamwork_preview_reviewer`
   - Scope: Review of Slices 0–10, rollback points, risk/blocker checks against A1–A30, verification criteria.
   - Working Directory: `.agents/teamwork/review_migration_slices_1`

8. **Forensic Integrity Auditor**
   - Type: `teamwork_preview_auditor`
   - Scope: Verification of evidence fidelity, citations, absence of fabricated line numbers, strict adherence to A1–A30 and current HEAD state.
   - Working Directory: `.agents/teamwork/auditor_synthesis_1`

## Phased Execution Strategy
- **Phase 1: Deep Parallel Audits (Agents 1–5)**
  Dispatch 5 specialized explorer agents to perform thorough code audits citing concrete file paths and line numbers at HEAD (`ced1cbc`).
- **Phase 2: Worker / Job / IPC Design (Agent 6)**
  Dispatch worker/IPC designer armed with audit insights to craft concrete protocol specs, DTOs, session state machines, and streaming architectures.
- **Phase 3: Master Synthesis (Orchestrator)**
  Synthesize all 7 audits and designs into `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\PRE_IMPLEMENTATION_PLAN.md` covering all 24 required sections and Slices 0–10 in granular detail.
- **Phase 4: Independent Review & Forensic Verification (Agents 7 & 8)**
  Dispatch Reviewer to validate against A1–A30 and check rollback points and risk classifications. Dispatch Forensic Auditor to verify citation accuracy and ensure zero cheating/fabrication.
- **Phase 5: Final Delivery & Victory Reporting**
  Package final state, update all state tracking files, and report complete findings to sentinel.
