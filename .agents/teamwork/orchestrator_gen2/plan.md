# Orchestration Plan — Generation 2

## Mission
Orchestrate the completion of the evidence-driven architectural audit, design the Worker / Job / IPC topology, synthesize the authoritative 24-Section Pre-Implementation Deliverable and Slices 0–10 Implementation Plan enforcing Invariants A1–A30, and conduct verification/migration review.

## Phases and Milestones

### Phase 1: Complete Foundational Architectural Audits
- **Status of Audits D, E, F**: Already completed and verified:
  - Audit E (Rust Runtime & Concurrency): `.agents/teamwork/audit_rust_runtime_1/audit_report.md`
  - Audit D (Pure-Python & Test Architecture): `.agents/teamwork/audit_pure_python_test_1/audit_report.md`
  - Audit F (Model Management Consolidation): `.agents/teamwork/audit_model_management_1/audit_report.md`
- **Milestone 1.1: Audit A, C, G (Architecture & Dependencies)**
  - Dispatch Explorer (`audit_arch_dep_2`) to audit:
    - Audit A: Process topology (NVDA, Python plugin, host.exe, LiteRT, llama, PyO3, subprocesses)
    - Audit C: NVDA import contamination across all packages, pure Python boundary definition
    - Audit G: Detailed deconstruction of `plugin/background.py`
- **Milestone 1.2: Audit B & Thread Affinity (Audits A, B, Invariants A1–A4, A27)**
  - Dispatch Explorer (`audit_nvda_thread_2`) to audit:
    - Thread & executor map across production modules (`background.py`, `application.py`, `local_provider_startup.py`, `ui/task_runner.py`, `ui/adapter.py`, `ui/host_transport.py`, `ui/host_process.py`, `service/model_cache.py`)
    - Classification: KEEP IN NVDA, MOVE TO PURE PYTHON, MOVE TO WORKER, RUST-OWNED, REMOVE/CONSOLIDATE
    - Strict enforcement of NVDA event/main thread affinity and thin accessibility shell (A1–A4, A27)

### Phase 2: Worker / Job / IPC Architecture Design
- **Milestone 2.1: Worker, Job & IPC Implementation Design**
  - Dispatch Worker/Designer (`design_worker_ipc_1`) to produce comprehensive technical design:
    - Worker process lifecycle, versioned handshake, framing, bi-directional IPC (Invariants A16–A24)
    - Job/session state machine (lifecycle, cancel, eviction, terminal states)
    - Immutable DTO definitions (JobSubmission, JobUpdate, SessionConfig, StreamChunk, ResultPayload)
    - Bounded streaming session foundations for OCR (frame dropping) and Transcription (bounded audio buffer, partial vs finalized transcripts) (Slices 9–10)
    - Integration contracts with Slices 2–4

### Phase 3: Synthesis of Authoritative 24-Section Pre-Implementation Deliverable
- **Milestone 3.1: Deliverable Synthesis**
  - Dispatch Synthesis Worker/Explorer (`auditor_synthesis_1`) to compile all findings from Audits A–G and Worker/IPC Design into the definitive 24-section deliverable in `.agents/teamwork/architecture_deliverable.md`:
    1. Current process topology
    2. Target process topology
    3. Current dependency graph
    4. Target dependency graph
    5. Complete thread/executor map
    6. NVDA import map
    7. Test-tier redesign
    8. Rust supervisor audit & findings
    9. LiteRT flow
    10. llama flow
    11. Current model responsibility map
    12. Target model-management decomposition
    13. Current background-task map
    14. Worker IPC design (versioning, handshake, protocol)
    15. Job/session state model
    16. Immutable DTO definitions
    17. Migration slices (Slices 0–10 detailed plans)
    18. Acceptance tests per slice
    19. Rollback points
    20. Packaging implications (.nvda-addon, SCons, wheel packaging)
    21. Worker/runtime recovery strategy
    22. Accessibility impact
    23. Performance/resource limits
    24. Risks, blockers, and classified findings (CONFIRMED, LIKELY, DESIGN DETAIL, BLOCKER, UNKNOWN)

### Phase 4: Migration / Regression Review & Baseline Verification
- **Milestone 4.1: Review of Slices 0–10 against Invariants A1–A30**
  - Dispatch Reviewer (`review_migration_slices_1`) to review the complete synthesis deliverable:
    - Audit Invariants A1–A30 compliance
    - Verify rollback points, risk/blocker classifications
    - Run baseline tool checks (`uv run ruff check .`, `uv run pytest`, `cargo check --manifest-path nvda_ui_host/Cargo.toml`, `cargo test --manifest-path runtime_supervisor/Cargo.toml`)
- **Milestone 4.2: Forensic Audit**
  - Dispatch Forensic Auditor (`teamwork_preview_auditor`) to verify zero cheating, genuine code citations, complete evidence chains, and strict invariant adherence.

### Phase 5: Final Orchestrator Synthesis & Handoff to Sentinel
- Collect all gate verdicts in `GATE_STATUS.md`.
- Produce final handoff and victory report to Sentinel.
