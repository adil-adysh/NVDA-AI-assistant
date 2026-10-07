# Handoff Report: Adversarial Challenge for Milestone 1 (Slice 2 — Job Domain & Versioned Protocol)

**Author:** Challenger 1 (Empirical Challenger)  
**Date:** 2026-10-05T04:25:00Z  
**Type:** Hard Handoff (Challenge Review Complete)  
**Recipient:** `eb8f4e3d-cb67-4981-b12a-2c54cfb91f1d`  
**Working Directory:** `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\challenger_slice2_1`  
**Verdict:** `REQUEST_CHANGES`

---

## 1. Observation

An empirical, adversarial test suite was authored at `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\challenger_slice2_1\verify_adversarial.py` testing the production code under `addon/globalPlugins/AI-assistant/core/job/`.

Execution command:
```pwsh
uv run python .agents\teamwork\challenger_slice2_1\verify_adversarial.py
```

### Verbatim Tool Command Output:
```
=== Category 1: DTO Immutability & Slot Enforcement ===
  [PASS] 1.1 Direct attribute mutation rejected by FrozenInstanceError
  [PASS] 1.2 Adding dynamic attribute rejected by slots without __dict__
  [PASS] 1.3 DTO has slots=True and no __dict__
  [PASS] 1.4 Tuple collections reject item assignment (TypeError)
  [PASS] 1.5 JobResult __post_init__ rejects non-terminal status (RUNNING)
  [NOTE] 1.6 DTO payload dict is mutable in-place (standard Python dataclass behavior; to_dict uses defensive dict() copy)
  [PASS] 1.6 DTO nested dictionary behavior observed and classified

=== Category 2: Monotonic State Machine Guarantees ===
  [PASS] 2.1 Valid transition SUBMITTED -> RUNNING
  [PASS] 2.2 Backward transition RUNNING -> QUEUED raises InvalidStateTransitionError
  [PASS] 2.3 Backward transition RUNNING -> SUBMITTED raises InvalidStateTransitionError
  [PASS] 2.4 Transition RUNNING -> COMPLETED via record_result
  [PASS] 2.5 Terminal transition COMPLETED -> RUNNING raises TerminalStateError
  [PASS] 2.6 Terminal transition COMPLETED -> FAILED raises TerminalStateError
  [PASS] 2.7 Terminal transition FAILED -> COMPLETED raises TerminalStateError
  [PASS] 2.8 Progress on terminal state raises TerminalStateError
  [PASS] 2.9 Direct jump SUBMITTED -> COMPLETED raises InvalidStateTransitionError
  [FAIL] 2.10 Generation atomicity on rejected transition: BUG: generation changed from 1 to 10 despite TerminalStateError! Generation state was modified before terminal check.
  [FAIL] 2.10b Generation atomicity on rejected progress: BUG: generation changed from 1 to 20 despite TerminalStateError! Generation state was modified before terminal check.
  [FAIL] 2.10c SessionStateMachine generation atomicity on rejected transition: BUG: session generation changed from 1 to 15 despite TerminalStateError! Generation state was modified before terminal check.
  [FAIL] 2.10d record_result generation atomicity on rejected transition: BUG: generation changed from 1 to 12 despite InvalidStateTransitionError! Generation state was modified before validation check.

=== Category 3: Single-Result Invariant ===
  [PASS] 3.1 Second record_result raises TerminalStateError
  [PASS] 3.1b Single-result remains the first recorded result
  [PASS] 3.2 Concurrent record_result contention: exactly 1 winner, 29 TerminalStateError

=== Category 4: Cancellation Concurrency & Deadlock Audit ===
  [PASS] 4.1 50 concurrent cancel() calls: is_cancelled=True, callback fired exactly once
  [PASS] 4.2 Callback exception safely suppressed without disrupting subsequent callbacks
  [PASS] 4.3 Nested callback registration during cancellation executes safely
  [FAIL] 4.4 CancellationCoordinator re-entrancy deadlock audit: CRITICAL DEADLOCK DETECTED! CancellationCoordinator.request_cancellation holds non-reentrant Lock while invoking token.cancel(), causing permanent deadlock when a cancellation callback queries the coordinator (e.g. get_token, unregister_token, is_preemption_due).

=== Category 5: Stale Generation Fencing ===
  [PASS] 5.1 Stale transition generation (4 < 5) raises InvalidStateTransitionError
  [PASS] 5.2 Equal generation transition accepted
  [PASS] 5.3 Higher generation transition (6 > 5) advances active generation
  [PASS] 5.4 Stale progress generation (5 < 6) raises InvalidStateTransitionError
  [PASS] 5.5 Stale result generation (5 < 6) raises InvalidStateTransitionError
  [PASS] 5.6 Session FSM stale generation (2 < 3) raises InvalidStateTransitionError

=== Category 6: Protocol Framing Adversarial Injection ===
  [PASS] 6.1 Corrupt magic bytes raises ProtocolError(INVALID_FRAME)
  [PASS] 6.2 Lying binary frame length header raises ProtocolError(INVALID_FRAME)
  [PASS] 6.3 Binary frame < 12 bytes raises ProtocolError(INVALID_FRAME)
  [PASS] 6.4 Oversized NDJSON encode raises ProtocolError(FRAME_TOO_LARGE)
  [PASS] 6.5 Empty whitespace NDJSON raises ProtocolError(INVALID_FRAME)
  [PASS] 6.6 Handshake major version mismatch rejected (accepted=False)
  [PASS] 6.7 Malformed SemVer strings safely return False without exception

=== Category 7: Schema Validation Adversarial Fuzzing ===
  [PASS] 7.1 Boolean passed for integer caught by validator (integer != bool distinction)
  [PASS] 7.2 Float passed for integer rejected by validator
  [PASS] 7.3 progress_pct > 100.0 rejected with maximum range check
  [PASS] 7.4 Injected additional property rejected by additionalProperties: False
  [PASS] 7.5 Const mismatch rejected by validator

============================================================
ADVERSARIAL SUITE SUMMARY: 39 PASSED, 5 FAILED
============================================================
```

### Direct Code Citations for Observed Defects:

#### Defect 1: Re-entrancy Deadlock in `CancellationCoordinator.request_cancellation`
- **File**: `addon/globalPlugins/AI-assistant/core/job/cancellation.py`
- **Lines 142–160**:
  ```python
  def request_cancellation(
      self,
      job_id: str,
      reason: str = "user_cancelled",
      preemption_timeout: float = 3.0,
  ) -> bool:
      with self._lock:
          token = self._tokens.get(job_id)
          if token is None:
              return False
          token.cancel(reason)
          self._deadlines[job_id] = time.monotonic() + preemption_timeout
          return True
  ```
- **Line 122**:
  ```python
  self._lock = threading.Lock()
  ```
- **Lines 73–78** (`CancellationToken.cancel`):
  ```python
  for callback in callbacks_to_fire:
      try:
          callback()
      except Exception:
          pass
  ```
- **Observed Behavior**: `self._lock` is a non-reentrant `threading.Lock()`. `request_cancellation()` acquires `self._lock` and synchronously calls `token.cancel()`. `token.cancel()` synchronously invokes all registered callbacks. If any callback interacts with the coordinator (`coord.get_token(job_id)`, `coord.is_preemption_due(job_id)`, `coord.unregister_token(job_id)`), the caller thread permanently deadlocks with itself. Furthermore, holding the coordinator lock during arbitrary callback execution blocks all other threads from performing any coordinator operations for all other jobs.

#### Defect 2: Non-Atomic State Transitions and Generation Corruption on Rejection
- **File**: `addon/globalPlugins/AI-assistant/core/job/state.py`
- **Lines 116–130** (`JobStateMachine.transition`):
  ```python
  with self._lock:
      if generation is not None:
          if generation < self._generation:
              raise InvalidStateTransitionError(...)
          if generation > self._generation:
              self._generation = generation

      if self._state.is_terminal:
          raise TerminalStateError(...)
  ```
- **Lines 149–161** (`JobStateMachine.record_progress`):
  ```python
  with self._lock:
      if progress.generation < self._generation:
          raise InvalidStateTransitionError(...)
      if progress.generation > self._generation:
          self._generation = progress.generation

      if self._state.is_terminal:
          raise TerminalStateError(...)
  ```
- **Lines 184–197** (`JobStateMachine.record_result`):
  ```python
  if result.generation < self._generation:
      raise InvalidStateTransitionError(...)
  if result.generation > self._generation:
      self._generation = result.generation

  allowed = _VALID_JOB_TRANSITIONS.get(self._state, frozenset())
  if result.status not in allowed:
      raise InvalidStateTransitionError(...)
  ```
- **Lines 294–308** (`SessionStateMachine.transition`):
  ```python
  with self._lock:
      if generation is not None:
          if generation < self._generation:
              raise InvalidStateTransitionError(...)
          if generation > self._generation:
              self._generation = generation

      if self._state.is_terminal:
          raise TerminalStateError(...)
  ```
- **Observed Behavior**: In all four methods, `self._generation` is mutated before verifying whether the state machine is terminal or whether the requested transition is valid. When `TerminalStateError` or `InvalidStateTransitionError` is raised, `self._generation` has already leaked and permanently mutated to the future generation. This violates terminal immutability (Invariant A21, A23) and corrupts generation fencing by causing subsequent legitimate updates to be erroneously rejected as stale.

---

## 2. Logic Chain

1. **Deadlock Vulnerability (Invariant A22)**:
   - Observation: `CancellationCoordinator._lock` is a non-reentrant `threading.Lock`. `request_cancellation` calls `token.cancel(reason)` inside `with self._lock:`.
   - `token.cancel(reason)` fires registered callbacks on the calling thread.
   - If a subscriber (e.g. presenter, worker client, or cleanup handler) checks token or deadline status via `coord.get_token(job_id)` or `coord.is_preemption_due(job_id)`, it attempts to acquire `self._lock`.
   - Because `threading.Lock` cannot be re-acquired by the same thread, the thread deadlocks indefinitely.
   - Verified empirically by Test 4.4: a background thread calling `coord.request_cancellation()` with a callback that invokes `coord.get_token()` failed to finish within 500ms and deadlocked the thread.

2. **Generation Leakage on Terminal State & Invalid Transitions (Invariant A21, A23)**:
   - Observation: Terminal states (`COMPLETED`, `FAILED`, `CANCELLED`, `CLOSED`, `ERROR`) are defined as irreversible and immutable.
   - However, in `JobStateMachine.transition()`, `JobStateMachine.record_progress()`, and `SessionStateMachine.transition()`, if an update packet arrives with `generation > self._generation`, the generation number is updated *before* checking `if self._state.is_terminal:`.
   - In `JobStateMachine.record_result()`, if a result arrives with an invalid transition (e.g. `COMPLETED` on a `SUBMITTED` job), the generation number is updated *before* checking `if result.status not in allowed:`.
   - Consequence: A rogue, misordered, or invalid wire packet mutates the generation counter of an otherwise terminal or unchanged state machine. If an invalid packet carries generation 99, all subsequent legitimate updates with generation 2..98 are rejected as "stale", corrupting the generation fence.
   - Verified empirically by Tests 2.10, 2.10b, 2.10c, and 2.10d.

3. **Required Remediations**:
   - In `CancellationCoordinator`:
     Take token reference and record deadline under `self._lock`, but invoke `token.cancel(reason)` *outside* `self._lock` (identical to the pattern already used in `cancel_all()` at lines 174–180). Alternatively or additionally, use `threading.RLock()`.
   - In `JobStateMachine` and `SessionStateMachine`:
     Check terminal state and transition validity *before* committing any generation advance, or only advance `self._generation` atomically at the moment the transition or update successfully completes.

---

## 3. Caveats

- **DTO Collections**: The dataclasses use `@dataclass(frozen=True, slots=True)` and tuple collections (`supported_schemas`, `requested_capabilities`, `bounding_boxes`). Attribute reassignment and dynamic attribute injections are strictly rejected. However, nested dictionary attributes (`spec.payload`, `result.result_data`, `failure.details`, `config.config_parameters`) are mutable standard Python dicts. Modifying `spec.payload["x"] = 1` mutates the inner dict in memory. This is standard Python dataclass behavior and serialization via `to_dict()` performs defensive `dict(...)` copies, but callers should be aware not to mutate nested payload dicts directly.
- **Scope Restriction**: Review was conducted purely within Milestone 1 (Slice 2). Named Pipe transport and multi-process worker lifecycle belong to Milestone 2 (Slice 3).

---

## 4. Conclusion

**Verdict: REQUEST_CHANGES**

Milestone 1 has high-quality foundation work (Draft 2020-12 pure-Python schema validation, NDJSON and 12-byte hybrid binary protocol framing, monotonic state transition definitions, and 0 NVDA import contamination). However, two clear bugs were empirically reproduced and must be fixed before proceeding to Milestone 2 (Slice 3):

1. **Fix Deadlock in `CancellationCoordinator.request_cancellation` (`addon/globalPlugins/AI-assistant/core/job/cancellation.py:142–160`)**:
   Do not hold `self._lock` while calling `token.cancel(reason)`. Store deadline and get token under lock, release lock, then invoke `token.cancel(reason)`.
2. **Fix Non-Atomic Generation Mutation in State Machines (`addon/globalPlugins/AI-assistant/core/job/state.py:108–202, 287–317`)**:
   In `JobStateMachine.transition`, `JobStateMachine.record_progress`, `JobStateMachine.record_result`, and `SessionStateMachine.transition`, check terminal state (`if self._state.is_terminal: raise TerminalStateError(...)`) and transition validity (`if next_state not in allowed: raise InvalidStateTransitionError(...)`) *before* mutating `self._generation`.

---

## 5. Verification Method

To independently verify these findings:

1. **Run the Adversarial Harness**:
   ```pwsh
   uv run python .agents\teamwork\challenger_slice2_1\verify_adversarial.py
   ```
   Expected before fix: Exits with code 1; 5 failed tests (Tests 2.10, 2.10b, 2.10c, 2.10d, 4.4).
   Expected after fix: Exits with code 0; all 44 tests pass cleanly.

2. **Run Pytest Suite**:
   ```pwsh
   uv run pytest tests/core/job/
   ```
   Verifies standard test suite passes.

3. **Run AST Boundary Validation**:
   ```pwsh
   uv run pytest tests/test_import_boundaries.py
   ```
