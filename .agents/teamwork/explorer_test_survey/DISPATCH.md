## 2026-10-05T03:30:43Z
You are Explorer 3 (Test & Verification Specialist) for Migration Slice 2 & Slice 3 of adil-adysh/NVDA-AI-assistant.
Your working directory is: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\explorer_test_survey

MANDATORY FIRST STEP:
Read D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\ORIGINAL_REQUEST.md in full. Do not skip or summarize.

INPUTS:
- Authoritative User Request: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\ORIGINAL_REQUEST.md (see timestamp 2026-10-05T01:52:03Z)
- Approved Architecture Deliverable: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\architecture_deliverable.md (Sections 7.1-7.2, 17, 18, Invariants A4, A6, A19, A30)
- Prior handoff: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\orchestrator_slice0_1_gen2\handoff.md
- Test suite structure: `tests/`, `tests/support/bootstrap.py`, `conftest.py`, `tests/test_import_boundaries.py`
- SCons build: `SConstruct`, `buildVars.py`

TASK:
Conduct an exhaustive technical survey of the Test Infrastructure, Verification Gates, and Adversarial Scenarios for Slice 2 & Slice 3.
1. Existing Test Environment & Baseline Gates:
   Inspect `tests/`, `conftest.py`, markers (`-m "not nvda_integration"`), and how tests run under `uv run pytest`.
   Document how baseline tests must run:
   - `uv run ruff check .`
   - `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml`
   - `cargo check --manifest-path nvda_ui_host/Cargo.toml`
   - `uv run pytest tests/test_import_boundaries.py`
   - `uv run pytest -m "not nvda_integration"`
2. Slice 2 Test Suite Architecture (Tier 1 Pure Python):
   - Structure tests under `tests/core/job/` or `tests/core/test_job_*.py`.
   - Coverage: all DTO creations, immutability checks, JSON schema validation (Draft 2020-12), state machine monotonic transitions, invalid transition rejections, cancellation token cooperative checks, protocol framing/encoding, and mock client implementations.
   - Enforce zero NVDA dependency in tests.
3. Slice 3 Test Suite Architecture (Tier 2 Multi-Process / Worker IPC):
   - Multi-process integration tests: spawning worker process, named pipe client/server connections, DACL security verification.
   - Protocol handshake verification: accepted vs rejected incompatible versions.
   - Heartbeat watchdog: missed pings timeout (15s), broken-pipe detection (<5ms).
   - Worker crash resilience & circuit breaker: killing worker during active job, killing worker while idle, testing >=3 crashes in 60s tripping circuit breaker to `FAILED_TRIPPED`, verifying NVDA thread is never frozen or crashed.
   - Trivial compute job: submission, progress streaming, completion, cancellation.
4. Import Boundary & SCons Packaging Verification:
   - Verify that adding `addon/globalPlugins/AI-assistant/core/job/` and `worker/` conforms to `tests/test_import_boundaries.py`.
   - Verify that `uv run scons --dry-run` packaging graph remains clean and excludes tests.

OUTPUT:
Write your complete survey report to:
`D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\explorer_test_survey\report.md`
Then call `send_message` to recipient `eb8f4e3d-cb67-4981-b12a-2c54cfb91f1d` with your summary.
Do NOT modify production code. This is a read-only investigation.
