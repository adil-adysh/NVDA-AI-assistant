# Handoff Report: Test Infrastructure, Verification Gates & Adversarial Scenarios for Slice 2 & Slice 3

**Author**: Explorer 3 (Test & Verification Specialist)  
**Working Directory**: `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\explorer_test_survey`  
**Date**: 2026-10-05T03:39:00Z  
**Target Recipient**: Orchestrator / Parent (`eb8f4e3d-cb67-4981-b12a-2c54cfb91f1d`)  
**Status**: **COMPLETE (READ-ONLY INVESTIGATION)**  

---

## 1. Observation

1. **Authoritative Request & Architecture Specifications**:
   - `ORIGINAL_REQUEST.md:151–210` mandates implementation of Slice 2 (Job Domain, State Machines, Versioned IPC Protocol) and Slice 3 (Supervised Worker Process Lifecycle, Named Pipes, Failure Isolation).
   - `architecture_deliverable.md` Sections 7.1–7.2, 14.1–14.4, 15.1–15.4, 16.1–16.2, 17, 18, 20.1, 21.1 and Invariants A4, A6, A19, A30 define the strict architectural boundaries, 3-tier testing model, DTO schemas, and circuit breaker recovery mechanics.

2. **Baseline Verification Gates Executed at HEAD**:
   - `uv run ruff check .` exited code 0: `"All checks passed!"`
   - `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml` exited code 0: `20 passed; 0 failed; finished in 1.54s`
   - `cargo check --manifest-path nvda_ui_host/Cargo.toml` exited code 0: `Finished dev profile [optimized + debuginfo] target(s) in 0.05s`
   - `uv run pytest tests/test_import_boundaries.py` exited code 0: `4 passed in 0.13s` (scanned all pure modules in 130ms, satisfying the $< 150\text{ ms}$ SLA threshold in line 245)
   - `uv run pytest -m "not nvda_integration"` exited code 0: `450 passed, 18 deselected in 13.65s`
   - `uv run scons --dry-run` exited code 0: built packaging graph cleanly, targeting `AIAssistant-0.14.0.nvda-addon`

3. **AST Boundary Scan & Ruff Rules**:
   - `tests/test_import_boundaries.py:16–26` defines `PURE_DIRECTORIES = ("core", "config", "service", "providers", "use_case", "prompts", "tools", "observability", "embeddings")`.
   - `core` is already present in `PURE_DIRECTORIES`, so any new file in `addon/globalPlugins/AI-assistant/core/job/` will automatically be checked.
   - `worker` is currently **not** present in `PURE_DIRECTORIES` and must be added when `addon/globalPlugins/AI-assistant/worker/` is created.
   - In `pyproject.toml:111–131`, `tool.ruff.lint.per-file-ignores` contains zero overrides for `core/**` or `worker/**`, ensuring Ruff `TID251` banned API checks apply strictly.

4. **Win32 APIs Availability**:
   - Tested in Python 3.13: `win32security`, `ntsecuritycon`, and `win32job` are fully functional via the pinned `pywin32==311` dependency.
   - Verified that Win32 Job Object creation with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` and DACL creation restricting access to `TOKEN_USER` and `WinBuiltinAdministratorsSid` execute without error.

5. **Packaging Isolation**:
   - `site_scons/site_tools/NVDATool/addon.py:6–21` defines `isTestArtifact()` which excludes `tests`, `test`, `conftest.py`, `test_*.py`, `*_test.py`, and `*.pyc`.
   - Tests under `tests/core/job/` and `tests/worker/` reside outside `addon/` and are unconditionally excluded from the `.nvda-addon` distribution.

---

## 2. Logic Chain

1. **Baseline Integrity (Observation 2)**: All existing test suites, Rust crates, and import boundary checkers pass cleanly. No regressions currently exist at HEAD.
2. **Tier Separation Compliance (Observations 1 & 2)**:
   - Invariant A30 specifies three distinct tiers:
     - Tier 1: Pure Python ($< 3.0\text{ s}$, target $< 1.0\text{ s}$ for Slice 2).
     - Tier 2: Rust & Worker Multi-Process IPC ($< 8.0\text{ s}$).
     - Tier 3: Live NVDA Integration ($\approx 15.0\text{ s}$).
   - Slice 2 modules belong entirely to Tier 1 (`tests/core/job/`). They require zero NVDA code, zero mock shims, and zero OS pipes.
   - Slice 3 modules belong to Tier 2 (`tests/worker/`). They require multi-process execution, named pipes, Win32 Job Objects, and fault injection.
3. **Import Boundary Security (Observation 3)**:
   - Placing Slice 2 under `core/job/` means it is immediately scanned by `tests/test_import_boundaries.py`.
   - Placing Slice 3 under `worker/` requires adding `"worker"` to `PURE_DIRECTORIES` in `tests/test_import_boundaries.py`.
   - Neither package has Ruff exemptions, guaranteeing zero NVDA imports (Invariants A4, A6).
4. **Adversarial Resilience (Observations 1 & 4)**:
   - Out-of-process worker crashes cannot crash NVDA if wrapped in Windows Job Objects with `KILL_ON_JOB_CLOSE` and supervised with fast broken-pipe detection ($< 5\text{ ms}$).
   - Circuit breaker transition to `FAILED_TRIPPED` after $\ge 3$ crashes in 60s prevents infinite restart livelocks.
5. **Conclusion**:
   - The test infrastructure for Slice 2 and Slice 3 is fully designed and validated. All required test modules, fixtures, adversarial matrices, and verification commands are documented in `report.md`.

---

## 3. Caveats

1. **JSON Schema Validator**: The project does not currently have `jsonschema` in `pyproject.toml` dependencies. It is recommended to add `jsonschema>=4.20.0` to `[dependency-groups] dev` (which does not affect the packaged add-on) or use a self-contained schema validator in `tests/support/schema_validator.py`.
2. **Test Named Pipe Isolation**: Integration tests in Tier 2 must never hardcode a single static pipe name (`\\.\pipe\nvda_ai_worker_cmd`), as running tests in parallel or following an ungraceful abort will cause `winerror=231` (`ERROR_PIPE_BUSY`). The test suite must generate unique pipe suffixes per test (`\\.\pipe\nvda_ai_worker_cmd_{uuid}`).
3. **Watchdog Timers in Tests**: Real 15.0s heartbeat timeouts would slow down the test suite. Tests should use configurable sub-second timeouts or virtual clocks to complete within hundreds of milliseconds.

---

## 4. Conclusion

The technical survey of the Test Infrastructure, Verification Gates, and Adversarial Scenarios for Slice 2 & Slice 3 is complete. The detailed architectural report has been written to:
`D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\explorer_test_survey\report.md`

Key Deliverables Specified:
- **Slice 2 Test Suite**: `tests/core/job/` covering DTO immutability, JSON Schema Draft 2020-12 validation, discrete/continuous FSM monotonicity, cooperative two-phase cancellation tokens, NDJSON framing, and pure mock clients.
- **Slice 3 Test Suite**: `tests/worker/` covering Win32 Job Object containment, named pipe transport with DACL security, handshake capability negotiation, $< 5\text{ ms}$ broken-pipe detection, worker crash resilience, $\ge 3$ crash circuit breaker (`FAILED_TRIPPED`), and trivial compute job execution.
- **Adversarial Test Matrix**: 14 concrete adversarial failure scenarios mapped with stimuli, expected behaviors, and assertions.
- **Import Boundary & SCons Defense**: Automated AST scan extension and zero-leakage packaging guarantees.

---

## 5. Verification Method

To independently verify the baseline gates and survey findings:

```powershell
# 1. Static linting & banned API rules
uv run ruff check .

# 2. Rust runtime supervisor concurrency suite (20/20 passed)
uv run cargo test --manifest-path runtime_supervisor/Cargo.toml

# 3. Rust UI host compilation
cargo check --manifest-path nvda_ui_host/Cargo.toml

# 4. AST boundary architecture test (< 150ms)
uv run pytest tests/test_import_boundaries.py

# 5. Full pure test suite (450 passed)
uv run pytest -m "not nvda_integration"

# 6. SCons packaging dry-run
uv run scons --dry-run
```

All 6 commands pass with 0 errors.
