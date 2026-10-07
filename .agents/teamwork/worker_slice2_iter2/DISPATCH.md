## 2026-10-05T04:24:37Z
You are Worker 2 (Milestone 1 Remediation Worker) for Migration Slice 2 & Slice 3 of adil-adysh/NVDA-AI-assistant.
Your working directory is: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\worker_slice2_iter2

MANDATORY FIRST STEP:
Read D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\ORIGINAL_REQUEST.md in full. Do not skip or summarize.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

INPUTS:
- Authoritative User Request: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\ORIGINAL_REQUEST.md
- Project Scope Document: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\orchestrator_slice2_3_gen2\PROJECT.md
- Challenger 1 Handoff Report: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\challenger_slice2_1\handoff.md
- Challenger 2 Handoff Report: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\challenger_slice2_2\handoff.md
- Reviewer 2 Handoff Report: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\reviewer_slice2_2\handoff.md
- Adversarial Test Script: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\challenger_slice2_1\verify_adversarial.py
- Existing files under `addon/globalPlugins/AI-assistant/core/job/` and `tests/core/job/`

TASK SPECIFICATION:
Remediate the defects identified by Challenger 1, Challenger 2, and Reviewer 2:

1. FIX RE-ENTRANCY DEADLOCK in `addon/globalPlugins/AI-assistant/core/job/cancellation.py`:
   - Change `self._lock = threading.Lock()` to `self._lock = threading.RLock()` in `CancellationCoordinator`.
   - In `CancellationCoordinator.request_cancellation()`:
     Look up `token` and set `self._deadlines[job_id]` inside `with self._lock:`.
     Then, invoke `token.cancel(reason)` OUTSIDE `self._lock`. This ensures no deadlock occurs when cancellation callbacks synchronously query the coordinator (e.g. `get_token`, `is_preemption_due`, `unregister_token`).
   - In `CancellationCoordinator.cancel_all()`:
     Snapshot `tokens = list(self._tokens.values())` and record deadlines under `with self._lock:`.
     Then, call `token.cancel(reason)` on each token OUTSIDE `self._lock`.

2. FIX PREMATURE GENERATION ADVANCEMENT in `addon/globalPlugins/AI-assistant/core/job/state.py`:
   - In `JobStateMachine.transition()`:
     Verify `generation < self._generation` (raise `InvalidStateTransitionError`).
     Verify `self._state.is_terminal` (raise `TerminalStateError`).
     Verify `target in allowed` (raise `InvalidStateTransitionError`).
     ONLY AFTER all validation checks pass: update `self._state`, update `self._active_snapshot`, and update `if generation is not None and generation > self._generation: self._generation = generation`.
   - In `JobStateMachine.record_progress()`:
     Verify `progress.generation < self._generation` (raise `InvalidStateTransitionError`).
     Verify `self._state.is_terminal` (raise `TerminalStateError`).
     ONLY AFTER validation checks pass: update `self._active_snapshot` and update `if progress.generation > self._generation: self._generation = progress.generation`.
   - In `JobStateMachine.record_result()`:
     Verify `result.generation < self._generation` (raise `InvalidStateTransitionError`).
     Verify `self._state.is_terminal` or `self._result is not None` (raise `TerminalStateError`).
     Verify `result.status in allowed` (raise `InvalidStateTransitionError`).
     ONLY AFTER validation checks pass: update `self._state`, `self._result`, and update `if result.generation > self._generation: self._generation = result.generation`.
   - In `SessionStateMachine.transition()`:
     Verify `generation < self._generation` (raise `InvalidStateTransitionError`).
     Verify `self._state.is_terminal` (raise `TerminalStateError`).
     Verify `target in allowed` (raise `InvalidStateTransitionError`).
     ONLY AFTER validation checks pass: update `self._state` and update `if generation is not None and generation > self._generation: self._generation = generation`.

3. PROTOCOL & SCHEMA HARDENING:
   - In `addon/globalPlugins/AI-assistant/core/job/schemas.py`:
     In numeric range checks, reject `math.isnan(val)` or `math.isinf(val)`.
   - In `addon/globalPlugins/AI-assistant/core/job/protocol.py`:
     In NDJSON and binary frame decoders, verify that parsed JSON is a `dict` (`isinstance(data, dict)`), raising `ProtocolError(ErrorCode.INVALID_FRAME, "Frame payload must be a JSON object")` if a non-dict primitive (int, str, list, bool) is passed.

4. TEST SUITE UPDATES in `tests/core/job/`:
   - In `tests/core/job/test_cancellation.py`: Add test verifying that a cancellation callback querying coordinator methods during `request_cancellation()` completes without deadlock.
   - In `tests/core/job/test_state_machine.py`: Add tests verifying that `generation` is NOT modified when `TerminalStateError` or `InvalidStateTransitionError` is raised.
   - In `tests/core/job/test_protocol.py` and `test_schemas.py`: Add tests for non-dict frame rejection and NaN/Inf rejection.

5. VERIFICATION COMMANDS:
   Execute and verify:
   - `uv run python .agents\teamwork\challenger_slice2_1\verify_adversarial.py` (Must pass all categories, including Category 2 and Category 4!)
   - `uv run ruff check .` (0 errors)
   - `uv run pytest tests/test_import_boundaries.py` (4/4 passed)
   - `uv run pytest tests/core/job/` (All tests pass)
   - `uv run pytest -m "not nvda_integration"` (All pass, 0 regressions)

OUTPUT:
Write your handoff report to:
`D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\worker_slice2_iter2\handoff.md`
Report verification command outputs, modified files, and completion status.
Then send a completion message to recipient `eb8f4e3d-cb67-4981-b12a-2c54cfb91f1d`.
