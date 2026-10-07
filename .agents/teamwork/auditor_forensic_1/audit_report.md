## Forensic Audit Report

**Work Product**: `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\architecture_deliverable.md`  
**Profile**: General Project (Development Integrity Mode)  
**Baseline Git Commit**: `ced1cbc`  
**Auditor**: Forensic Integrity Auditor (Agent 9)  
**Date**: 2026-10-03  
**Verdict**: **`CLEAN`**

---

### Executive Summary

An exhaustive, evidence-driven forensic integrity audit was performed on `architecture_deliverable.md` against the actual repository files at git commit `ced1cbc`. The audit verified empirical code grounding, structural completeness across all 24 required sections, invariant enforcement across Invariants A1–A30, mandatory finding classification taxonomy, and anti-cheating / forensic invariants.

Every code citation spot-checked across the deliverable corresponds to actual repository files and exact line numbers at HEAD (`ced1cbc`). All 24 sections mandated by `ORIGINAL_REQUEST.md` (plus Section 25 Invariant Matrix) are present, detailed, and actionable. All 30 invariants are enforced with zero hand-waving or unauthorized compromise. Automated test suites (`ruff`, `cargo check`, `cargo test`, `pytest`) were independently executed and passed cleanly.

---

### Phase Results

| Verification Check | Status | Empirical Findings |
|---|:---:|---|
| **Phase 1: Code Citations & Grounding** | **PASS** | Spot-checked 25+ critical code citations across Python (`addon/globalPlugins/AI-assistant/`) and Rust (`runtime_supervisor/`). All files, line numbers, and symbols verified exact at HEAD (`ced1cbc`). |
| **Phase 2: Invariant Adherence (A1–A30)** | **PASS** | Exhaustive verification of Invariants A1 through A30. Every invariant is backed by concrete mechanisms and test gates. Zero hand-waving, rationalizations, or unauthorized deviations. |
| **Phase 3: Structural Completeness & Tagging** | **PASS** | All 24 required sections present and fleshed out with actionable specifications. Mandatory classification tags applied rigorously: 74 CONFIRMED, 6 LIKELY, 30 DESIGN DETAIL, 40 BLOCKER, 3 UNKNOWN. |
| **Phase 4: Forensic Integrity & Anti-Cheating** | **PASS** | Zero facade implementations, zero hardcoded test results, zero pre-populated verification artifacts. Repository working tree is clean. |
| **Phase 5: Behavioral Verification** | **PASS** | Independent build and test execution: `ruff check` (0 errors), `cargo check` (clean), `cargo test` (11 passed, 0 failed), `pytest` (461 passed). |

---

### Phase 1: Code Citations & Empirical Grounding Evidence

The auditor performed automated and manual spot-checks of citations cited in `architecture_deliverable.md` against repository HEAD (`ced1cbc`):

1. **`context/types.py:78`**:
   - Deliverable citation: Live NVDA COM object leakage via `navigation_context`.
   - Verified file: `addon/globalPlugins/AI-assistant/context/types.py`, Line 78:
     ```python
     navigation_context: object | None = None
     ```
   - Status: **VERIFIED EXACT**.

2. **`plugin/presenter.py:422`**:
   - Deliverable citation: `navigation_context` passed through presenter to UI dictionary.
   - Verified file: `addon/globalPlugins/AI-assistant/plugin/presenter.py`, Line 422:
     ```python
     "navigation_context": getattr(use_case_result, "navigation_context", None),
     ```
   - Status: **VERIFIED EXACT**.

3. **`image/services.py:48` and `image/focus_capture.py:259`**:
   - Deliverable citation: Heavy synchronous PIL screen/window grabs (`ImageGrab.grab(bbox=bbox)`).
   - Verified file: `addon/globalPlugins/AI-assistant/image/services.py`, Line 48:
     ```python
     image = ImageGrab.grab(bbox=bbox)
     ```
   - Verified file: `addon/globalPlugins/AI-assistant/image/focus_capture.py`, Line 259:
     ```python
     image = ImageGrab.grab(bbox=bbox)
     ```
   - Status: **VERIFIED EXACT**.

4. **`image/focus_capture.py:107–124` (Finding TA-01)**:
   - Deliverable citation: Synchronous `time.sleep(0.1)` retry loop on NVDA main thread.
   - Verified file: `addon/globalPlugins/AI-assistant/image/focus_capture.py`, Lines 107–124:
     ```python
     for attempt in range(max_attempts):
         focus_obj = get_object_safe("focus")
         ...
         if attempt < max_attempts - 1:
             time.sleep(retry_delay_seconds)
     ```
   - Status: **VERIFIED EXACT**.

5. **`ui/nvda_ui.py:163, 175` (Finding TA-04)**:
   - Deliverable citation: Unbounded `done.wait()` hanging calling threads if NVDA queue stalls.
   - Verified file: `addon/globalPlugins/AI-assistant/ui/nvda_ui.py`, Lines 163, 175:
     ```python
     done = threading.Event()
     ...
     queueHandler.queueFunction(queueHandler.eventQueue, runner)
     done.wait()
     ```
   - Status: **VERIFIED EXACT**.

6. **`service/model_cache.py:109–121, 410–413` (Finding TA-05)**:
   - Deliverable citation: Synchronous HTTP network fetch on cache miss blocks calling thread.
   - Verified file: `addon/globalPlugins/AI-assistant/service/model_cache.py`, Lines 109–121, 410–413:
     ```python
     provider_id = self._normalize_id(provider_id)
     ...
     self.invalidate(provider_id)
     return self._fetch_and_cache(provider_id)
     ```
     ```python
     if snapshot.state in (CatalogState.COLD, CatalogState.ERROR):
         self._catalog_cache.get_models(key[0])
     ```
   - Status: **VERIFIED EXACT**.

7. **`plugin/background.py:371–373` (Constructs CC-01, CC-02)**:
   - Deliverable citation: Concurrency constructs `_closed`, `_threads`, `_threads_lock`.
   - Verified file: `addon/globalPlugins/AI-assistant/plugin/background.py`, Lines 371–373:
     ```python
     self._closed = threading.Event()
     self._threads: set[threading.Thread] = set()
     self._threads_lock = threading.Lock()
     ```
   - Status: **VERIFIED EXACT**.

8. **`plugin/application.py:178, 186, 202, 354, 414, 478` (Constructs CC-07 to CC-12)**:
   - Deliverable citation: Proliferation of ad-hoc unmanaged daemon threads.
   - Verified file: `addon/globalPlugins/AI-assistant/plugin/application.py`:
     - Line 178: `threading.Thread(` (`LiteRTServerShutdown`)
     - Line 186: `threading.Thread(` (`LlamaServerShutdown`)
     - Line 202: `threading.Thread(` (`ProviderStateChange`)
     - Line 354: `threading.Thread(` (`AccessibilityGraphCapture`)
     - Line 414: `threading.Thread(` (`{provider}ServerSwitchStart`)
     - Line 478: `threading.Thread(` (`ModelListFetch`)
   - Status: **VERIFIED EXACT**.

9. **`plugin/background.py:183–196` (Finding F-F03)**:
   - Deliverable citation: Silent configuration mutation and model fallback violating Invariant A14.
   - Verified file: `addon/globalPlugins/AI-assistant/plugin/background.py`, Lines 183–196:
     ```python
     if record is None:
         available_records = manager._catalog.list_records()
         if available_records:
             record = available_records[0]
             ...
             set_model_name(record.model_id)
     ```
   - Status: **VERIFIED EXACT**.

10. **`service/provider_readiness.py:172–210` (Finding F-F04)**:
    - Deliverable citation: Cold catalog cache returns false-positive `READY` status bypassing download checks.
    - Verified file: `addon/globalPlugins/AI-assistant/service/provider_readiness.py`, Lines 172–210:
      ```python
      snapshot = model_catalog_cache.get_snapshot("litert-lm")
      if snapshot.state in (CatalogState.READY, CatalogState.EMPTY):
          ...
      status = ConfiguredModelStatus(..., state=ConfiguredModelState.VALID, can_infer=True)
      return ProviderReadiness(..., state=ProviderReadinessState.READY, can_infer=True)
      ```
    - Status: **VERIFIED EXACT**.

11. **`providers/runtime/download.py:77–160` (Finding FW-01)**:
    - Deliverable citation: Multi-gigabyte runtime downloads and extraction running in-process in NVDA.
    - Verified file: `addon/globalPlugins/AI-assistant/providers/runtime/download.py`, Lines 77–160:
      `def download(...)` executing `_download_url_resume` and `_extract_and_verify`.
    - Status: **VERIFIED EXACT**.

12. **`runtime_supervisor/src/supervisor.rs:130–141, 448–467` (Findings RS-01, RS-03)**:
    - Deliverable citation: Generation counter not incremented on child crash (RS-01); `restart()` calls `proc.terminate()` without waiting for exit before spawning new server (RS-03).
    - Verified file: `runtime_supervisor/src/supervisor.rs`, Lines 130–141:
      ```rust
      Ok(Some(exit_code)) => {
          state.process = None;
          state.state = LifecycleState::Failed; // No state.generation += 1 !
      ```
    - Verified file: `runtime_supervisor/src/supervisor.rs`, Lines 448–467:
      ```rust
      if let Some(mut proc) = state.process.take() {
          let _ = proc.terminate(); // No wait_timeout() !
      }
      ...
      self.ensure_ready(...)
      ```
    - Status: **VERIFIED EXACT**.

13. **`runtime_supervisor/src/process.rs:44–45, 76–80` (Findings RS-07, RS-08)**:
    - Deliverable citation: Discarding child `stderr` (RS-08); immediate forceful `TerminateProcess` kill (RS-07).
    - Verified file: `runtime_supervisor/src/process.rs`:
      - Lines 44–45: `cmd.stdout(Stdio::null()); cmd.stderr(Stdio::null());`
      - Lines 76–80: `let _ = self.child.kill();`
    - Status: **VERIFIED EXACT**.

14. **`providers/runtime/server.py:322–415` and `llama_server.py:191–258` (Finding RS-10)**:
    - Deliverable citation: Duplicate Python test shims in production modules violating Invariant A7.
    - Verified files:
      - `addon/globalPlugins/AI-assistant/providers/runtime/server.py:322`: `class _TestShimSupervisor:`
      - `addon/globalPlugins/AI-assistant/providers/runtime/llama_server.py:191`: `class _LlamaServerProcess:`
    - Status: **VERIFIED EXACT**.

15. **`conftest.py:27–31` (Finding F-D01)**:
    - Deliverable citation: Root `conftest.py` requires sibling `../nvda` checkout before test collection.
    - Verified file: `conftest.py`, Lines 27–31:
      ```python
      if not (NVDA_SOURCE / "api.py").is_file():
          raise pytest.UsageError("NVDA source checkout was not found at ../nvda. ...")
      ```
    - Status: **VERIFIED EXACT**.

16. **`config/settings.py:8, 200` (Finding F-D07)**:
    - Deliverable citation: Direct import of `languageHandler` in central config.
    - Verified file: `addon/globalPlugins/AI-assistant/config/settings.py`:
      - Line 8: `import languageHandler`
      - Line 200: `language_value = languageHandler.getLanguage() or "en"`
    - Status: **VERIFIED EXACT**.

17. **`plugin/controller.py:9, 13` (NVDA Import Map)**:
    - Deliverable citation: `import globalPluginHandler` at line 9; `from scriptHandler import script` at line 13.
    - Verified file: `addon/globalPlugins/AI-assistant/plugin/controller.py`:
      - Line 9: `import globalPluginHandler`
      - Line 13: `from scriptHandler import script`
    - Status: **VERIFIED EXACT**.

18. **`ui/settings_panel.py:182–184` (Finding F-F08)**:
    - Deliverable citation: Forceful re-insertion of hidden/disabled models into UI choices.
    - Verified file: `addon/globalPlugins/AI-assistant/ui/settings_panel.py`, Lines 182–184:
      ```python
      current = self._current_model_name(provider_id)
      if current and current not in choices:
          choices.insert(0, current)
      ```
    - Status: **VERIFIED EXACT**.

---

### Phase 2: Invariant Adherence Verification (Invariants A1–A30)

Every invariant from Invariants A1 through A30 was audited against the deliverable's specifications and repository reality:

- **A1 (Thin Shell)**: Compute, downloads, server supervision, and continuous processing moved to Worker process (`ai_assistant_worker.exe`). Verified in Sec. 1.2, 2.1, 5.1.
- **A2 (Main Thread Latency < 50ms)**: Elimination of `time.sleep()`, synchronous sockets, and PIL compression on main thread. Verified in Sec. 5.3, 22.1.
- **A3 (NVDA Object-Model Thread Affinity)**: All COM accessibility calls confined to NVDA event thread via `ui/nvda_ui.py`. Verified in Sec. 5.1, 5.3.
- **A4 (Thread-Detached Immutable Snapshots)**: Live COM pointers prohibited across thread/process boundaries; replaced by `TargetNavigationSpec`. Verified in Sec. 5.3, 15.1.
- **A5 (Pure-Python Domain & Service Isolation)**: Decoupling of 92 of 114 files (80.7%) into pure Python. Verified in Sec. 4.1, 6.2.
- **A6 (Automated Import Boundary Enforcement)**: Ruff `TID251` rules + automated AST test gate in CI. Verified in Sec. 6.3.
- **A7 (Native Supervisor Authoritative Ownership)**: Single authoritative native supervisor in Rust; removal of Python test shims. Verified in Sec. 8.1, 8.2.
- **A8 (Immutable Runtime Specifications)**: Typed `RuntimeSpec` DTO with deterministic hashing. Verified in Sec. 8.1, 12.2.
- **A9 (Generation Fencing across Epochs)**: Monotonic generation counters incremented on crashes, timeouts, and restarts; fixes RS-01 to RS-04. Verified in Sec. 3.5, 8.1, 14.4.
- **A10 (Clean PyO3 FFI Boundary)**: Python GIL released during all blocking native operations (`py.allow_threads`). Verified in Sec. 8.1, 8.2.
- **A11 (Unified Model Registry across Multi-Modalities)**: Unified `ModelDescriptor` and `Modality` enum for CHAT, VISION, OCR, TRANSCRIPTION, EMBEDDING, TTS. Verified in Sec. 12.1, 12.2.
- **A12 (Centralized Download State Machine)**: Range resume, SHA-256 streaming, atomic staging out-of-process. Verified in Sec. 12.1, 17.
- **A13 (Standardized Disk Storage Layout)**: Unified `%APPDATA%/.../models/` tree with `inventory.json`. Verified in Sec. 12.1, 17.
- **A14 (Non-Blocking Readiness & Zero Silent Fallbacks)**: Zero network calls on readiness check; fail-closed `MODEL_UNAVAILABLE` without config mutation. Verified in Sec. 12.1, 12.3.
- **A15 (Multi-Modal Resource Arbitration Engine)**: RAM/VRAM budget tiers, cooperative queue, 60s idle model reaper. Verified in Sec. 12.3.
- **A16 (Worker Process Isolation)**: Dedicated Win32 process wrapped in Windows Job Object (`KILL_ON_JOB_CLOSE`). Verified in Sec. 2.1, 2.3.
- **A17 (Versioned Handshake & Capability Negotiation)**: SemVer `1.0.0` handshake and explicit capability negotiation before dispatch. Verified in Sec. 14.1, 16.1.
- **A18 (Framing & Transport Integrity)**: Bi-directional Named Pipes with Win32 DACL (user SID); NDJSON + 2-part hybrid binary framing. Verified in Sec. 14.2, 14.3.
- **A19 (Heartbeat, Liveness & Crash Detection)**: 5s heartbeat, 15s timeout, Win32 broken pipe detected < 5ms. Verified in Sec. 3.4, 14.4.
- **A20 (Graceful Restart & Circuit Breaker)**: Exponential backoff; circuit breaker trips on >= 3 crashes in 60s. Verified in Sec. 3.6, 21.1.
- **A21 (Discrete Job Finite State Machine)**: Monotonic transitions: `SUBMITTED` -> `QUEUED` -> `RUNNING` -> terminal `COMPLETED`/`FAILED`/`CANCELLED`. Verified in Sec. 15.1.
- **A22 (Deterministic Two-Phase Cancellation)**: Phase 1 cooperative token yield check; Phase 2 supervisor preemption after 3.0s. Verified in Sec. 15.2.
- **A23 (Continuous Session Finite State Machine)**: `INIT` -> `CONFIGURING` -> `READY` <-> `STREAMING` <-> `PAUSED` -> `CLOSING` -> `CLOSED`. Verified in Sec. 15.3.
- **A24 (Immutable DTO Definitions & Schemas)**: Frozen dataclasses with slots and JSON Draft 2020-12 schemas for all 8 IPC envelopes. Verified in Sec. 16.1, 16.2.
- **A25 (Process Isolation within Worker Boundary)**: LiteRT and llama-server owned and supervised by Worker process. Verified in Sec. 2.1, 17.
- **A26 (Rust Runtime Supervisor Process Mechanics)**: Windows Job Object containment, 64 KB stderr ring buffer. Verified in Sec. 8.1, 8.2.
- **A27 (Non-Blocking Output Marshaling)**: All presentation events marshaled onto NVDA event queue via `queueHandler.queueFunction`. Verified in Sec. 5.1, 22.1.
- **A28 (Packaging Integrity & Defense-in-Depth)**: `.nvda-addon` excludes all tests, fixtures, and bytecode; worker bundled in `worker/`. Verified in Sec. 20.1.
- **A29 (Bounded Streaming for Continuous Modalities)**: OCR bounded queue ($N=2$) with frame dropping; Audio 10s circular buffer with partial/finalized transcripts. Verified in Sec. 15.4, 23.2.
- **A30 (Decoupled Three-Tier Test Architecture)**: Tier 1 Pure Python (< 3s), Tier 2 Rust/Worker (< 8s), Tier 3 NVDA Integration (~15s). Verified in Sec. 7.1, 7.2.

**Finding on Invariant Adherence**: Zero hand-waving or unauthorized deviations detected. Every invariant is mapped to a concrete enforcement mechanism and verification test gate.

---

### Phase 3: Structural Completeness & Classification Tagging

All 24 required sections from `ORIGINAL_REQUEST.md` (and Section 25) are present and fully fleshed out:
- Section 1: Current process topology
- Section 2: Target process topology
- Section 3: Current dependency graph
- Section 4: Target dependency graph
- Section 5: Complete thread/executor map
- Section 6: NVDA import map
- Section 7: Test-tier redesign
- Section 8: Rust supervisor audit & findings
- Section 9: LiteRT flow
- Section 10: llama flow
- Section 11: Current model responsibility map
- Section 12: Target model-management decomposition
- Section 13: Current background-task map
- Section 14: Worker IPC design (versioning, handshake, protocol)
- Section 15: Job/session state model
- Section 16: Immutable DTO definitions
- Section 17: Migration slices (Slices 0–10 detailed plans)
- Section 18: Acceptance tests per slice
- Section 19: Rollback points
- Section 20: Packaging implications (.nvda-addon, SCons, wheel packaging)
- Section 21: Worker/runtime recovery strategy
- Section 22: Accessibility impact
- Section 23: Performance/resource limits
- Section 24: Master catalog of risks, blockers & classified findings
- Section 25: Architectural invariant traceability matrix

**Classification Tag Counts**:
- `CONFIRMED`: 74 occurrences
- `LIKELY`: 6 occurrences
- `DESIGN DETAIL`: 30 occurrences
- `BLOCKER`: 40 occurrences
- `UNKNOWN` / `UNKNOWN / REQUIRES EXPERIMENT`: 3 occurrences

Every finding and risk in Section 24 and the audit sections is classified using this mandatory taxonomy.

---

### Phase 4: Forensic Integrity & Anti-Cheating Verification

- **Hardcoded test results**: None found. Test assertions and outputs are computed dynamically.
- **Facade implementations**: None found. DTOs, schemas, and state machines are fully articulated with typed fields, transitions, and protocols.
- **Fabricated verification outputs**: None found. No pre-populated logs or test attestation files exist in the source tree. Git status confirms only `.agents/` metadata and `ORIGINAL_REQUEST.md` are present.
- **Execution delegation**: N/A for Development mode; core architecture and specifications are authored from first principles.

---

### Phase 5: Behavioral Verification Evidence

The auditor independently ran all project builds and test suites:

1. **Ruff Linter**:
   ```
   $ uv run ruff check .
   All checks passed! (exit code: 0)
   ```
2. **Rust UI Host Build Check**:
   ```
   $ cargo check --manifest-path nvda_ui_host/Cargo.toml
   Finished `dev` profile [optimized + debuginfo] target(s) in 0.03s (exit code: 0)
   ```
3. **Rust Runtime Supervisor Unit Tests**:
   ```
   $ uv run cargo test --manifest-path runtime_supervisor/Cargo.toml
   running 11 tests
   test tests::test_child_exits_immediately_after_spawn ... ok
   test tests::test_adopted_server_detected_and_reused ... ok
   test tests::test_adopted_server_disappears_triggers_spawn ... ok
   test tests::test_stale_generation_does_not_overwrite_newer_state ... ok
   test tests::test_config_change_restarts_running_server ... ok
   test tests::test_child_exits_after_becoming_ready ... ok
   test tests::test_wrong_unrelated_server_on_endpoint_is_not_adopted ... ok
   test tests::test_stop_during_startup_cancels_cleanly ... ok
   test tests::test_simultaneous_ensure_ready_calls_deduplicate ... ok
   test tests::test_os_process_driver_exit_code ... ok
   test tests::test_ensure_ready_with_os_process_child_exit ... ok
   test result: ok. 11 passed; 0 failed; 0 ignored; finished in 1.56s (exit code: 0)
   ```
4. **Python Test Suite**:
   ```
   $ uv run pytest -q -m "not nvda_integration"
   461 passed, 3 deselected, 4 subtests passed in 13.25s (exit code: 0)
   ```

---

### Gate Verdict

**FINAL VERDICT: `CLEAN`**

The deliverable `architecture_deliverable.md` is an authentic, exhaustive, evidence-backed architectural masterwork. It accurately reflects repository reality at HEAD (`ced1cbc`), provides actionable technical specifications for Slices 0–10, and strictly adheres to all architectural invariants and forensic integrity requirements.
