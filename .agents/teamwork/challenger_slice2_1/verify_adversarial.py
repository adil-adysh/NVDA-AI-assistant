# -*- coding: utf-8 -*-
"""Adversarial and Empirical Verification Suite for Milestone 1 (Slice 2).

Tests:
1. DTO immutability and slot enforcement under reflection and mutation.
2. Monotonic state machine guarantees, illegal transitions, and generation atomicity.
3. Single-result invariant and multi-threaded terminal contention.
4. Concurrent cancellation triggers, callback exception safety, and coordinator re-entrancy deadlock audit.
5. Stale generation fencing across jobs and sessions.
6. Protocol framing adversarial injection and boundary testing.
7. Schema validation adversarial fuzzing (type confusion, boolean/integer, out-of-bounds).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import sys
import threading
import time
from typing import Any

# Ensure import paths include addon global plugins
sys.path.insert(0, r"D:\nvda-addons\NVDA-AI-assistant\addon\globalPlugins\AI-assistant")

from core.job.cancellation import (
	CancellationCoordinator,
	CancellationToken,
	JobCancelledError,
)
from core.job.client import MockJobClient, MockWorkerClient
from core.job.dto import (
	HandshakeRequest,
	HandshakeResponse,
	JobCancellationRequest,
	JobFailure,
	JobProgress,
	JobResult,
	JobSnapshot,
	JobSpec,
	JobStatus,
	ModalityType,
	SessionConfig,
	SessionState,
	StreamChunk,
	WorkerHealth,
)
from core.job.protocol import (
	MAX_FRAME_SIZE,
	PROTOCOL_VERSION,
	ErrorCode,
	ProtocolError,
	decode_binary_frame,
	decode_ndjson_frame,
	encode_binary_frame,
	encode_ndjson_frame,
	is_protocol_compatible,
	validate_handshake,
)
from core.job.schemas import (
	HANDSHAKE_REQUEST_SCHEMA,
	HANDSHAKE_RESPONSE_SCHEMA,
	JOB_PROGRESS_SCHEMA,
	JOB_RESULT_SCHEMA,
	JOB_SPEC_SCHEMA,
	SESSION_CONFIG_SCHEMA,
	STREAM_CHUNK_SCHEMA,
	WORKER_HEALTH_SCHEMA,
	ValidationError,
	validate_schema,
)
from core.job.state import (
	InvalidStateTransitionError,
	JobStateMachine,
	SessionStateMachine,
	TerminalStateError,
)


class TestRunner:
	def __init__(self) -> None:
		self.passed = 0
		self.failed = 0
		self.findings: list[str] = []

	def check(self, condition: bool, test_name: str, detail: str = "") -> bool:
		if condition:
			self.passed += 1
			print(f"  [PASS] {test_name}")
			return True
		else:
			self.failed += 1
			msg = f"  [FAIL] {test_name}: {detail}"
			print(msg)
			self.findings.append(msg)
			return False


runner = TestRunner()

# ===========================================================================
# CATEGORY 1: DTO Immutability & Slot Enforcement under Adversarial Mutation
# ===========================================================================
print("\n=== Category 1: DTO Immutability & Slot Enforcement ===")

# Test 1.1: Direct attribute mutation raises FrozenInstanceError
try:
	spec = JobSpec(job_id="job-001", job_type="test_compute")
	mutated = False
	try:
		spec.job_id = "job-002"  # type: ignore
		mutated = True
	except (FrozenInstanceError, AttributeError):
		pass
	runner.check(not mutated, "1.1 Direct attribute mutation rejected by FrozenInstanceError")
except Exception as e:
	runner.check(False, "1.1 Direct attribute mutation", str(e))

# Test 1.2: Adding dynamic attributes rejected by slots
try:
	added = False
	try:
		spec.dynamic_attr = "injected"  # type: ignore
		added = True
	except (AttributeError, FrozenInstanceError, TypeError):
		pass
	runner.check(not added, "1.2 Adding dynamic attribute rejected by slots without __dict__")
except Exception as e:
	runner.check(False, "1.2 Adding dynamic attribute", str(e))

# Test 1.3: Instance has no __dict__
has_dict = hasattr(spec, "__dict__")
runner.check(not has_dict, "1.3 DTO has slots=True and no __dict__")

# Test 1.4: Tuple collection immutability
try:
	req = HandshakeRequest(supported_schemas=("job.v1", "session.v1"))
	tuple_mutated = False
	try:
		req.supported_schemas[0] = "job.v2"  # type: ignore
		tuple_mutated = True
	except TypeError:
		pass
	runner.check(not tuple_mutated, "1.4 Tuple collections reject item assignment (TypeError)")
except Exception as e:
	runner.check(False, "1.4 Tuple collections", str(e))

# Test 1.5: JobResult __post_init__ rejects active status
try:
	invalid_res_created = False
	try:
		JobResult(job_id="job-001", status=JobStatus.RUNNING)
		invalid_res_created = True
	except ValueError:
		pass
	runner.check(
		not invalid_res_created, "1.5 JobResult __post_init__ rejects non-terminal status (RUNNING)"
	)
except Exception as e:
	runner.check(False, "1.5 JobResult status validation", str(e))

# Test 1.6: In-place mutation vulnerability of nested dictionary attributes
try:
	payload = {"original_param": 100}
	spec_with_dict = JobSpec(job_id="job-dict-test", job_type="test", payload=payload)
	# Adversarial attempt: mutate dictionary in place
	spec_with_dict.payload["original_param"] = 999
	# Check whether payload dictionary was mutated in-place
	dict_mutated = spec_with_dict.payload["original_param"] == 999
	if dict_mutated:
		runner.findings.append(
			"  [FINDING - DESIGN DETAIL] DTO nested dict 'spec.payload' is a mutable Python dict, "
			"allowing in-place mutation spec.payload['key'] = val despite @dataclass(frozen=True). "
			"Mitigation: consider MappingProxyType or deep defensive copy if strictly immutable DTO required."
		)
		print(
			"  [NOTE] 1.6 DTO payload dict is mutable in-place (standard Python dataclass behavior; to_dict uses defensive dict() copy)"
		)
	runner.check(True, "1.6 DTO nested dictionary behavior observed and classified")
except Exception as e:
	runner.check(False, "1.6 Nested dictionary immutability", str(e))

# ===========================================================================
# CATEGORY 2: Monotonic State Machine Guarantees & Atomicity
# ===========================================================================
print("\n=== Category 2: Monotonic State Machine Guarantees ===")

spec = JobSpec(job_id="job-fsm-001", job_type="test")
fsm = JobStateMachine(spec)

# Test 2.1: Transition to RUNNING
try:
	fsm.transition(JobStatus.RUNNING)
	runner.check(fsm.state == JobStatus.RUNNING, "2.1 Valid transition SUBMITTED -> RUNNING")
except Exception as e:
	runner.check(False, "2.1 Transition to RUNNING", str(e))

# Test 2.2: Backward transition RUNNING -> QUEUED
try:
	fsm.transition(JobStatus.QUEUED)
	runner.check(False, "2.2 Backward transition RUNNING -> QUEUED should fail")
except InvalidStateTransitionError:
	runner.check(True, "2.2 Backward transition RUNNING -> QUEUED raises InvalidStateTransitionError")
except Exception as e:
	runner.check(False, "2.2 Backward transition RUNNING -> QUEUED", f"Wrong error: {type(e)}")

# Test 2.3: Backward transition RUNNING -> SUBMITTED
try:
	fsm.transition(JobStatus.SUBMITTED)
	runner.check(False, "2.3 Backward transition RUNNING -> SUBMITTED should fail")
except InvalidStateTransitionError:
	runner.check(
		True, "2.3 Backward transition RUNNING -> SUBMITTED raises InvalidStateTransitionError"
	)
except Exception as e:
	runner.check(False, "2.3 Backward transition RUNNING -> SUBMITTED", f"Wrong error: {type(e)}")

# Test 2.4: Transition to terminal COMPLETED
try:
	res = JobResult(job_id="job-fsm-001", status=JobStatus.COMPLETED, duration_ms=50)
	fsm.record_result(res)
	runner.check(
		fsm.state == JobStatus.COMPLETED and fsm.is_terminal,
		"2.4 Transition RUNNING -> COMPLETED via record_result",
	)
except Exception as e:
	runner.check(False, "2.4 Transition to COMPLETED", str(e))

# Test 2.5: Terminal state mutation: COMPLETED -> RUNNING
try:
	fsm.transition(JobStatus.RUNNING)
	runner.check(False, "2.5 Terminal transition COMPLETED -> RUNNING should fail")
except TerminalStateError:
	runner.check(True, "2.5 Terminal transition COMPLETED -> RUNNING raises TerminalStateError")
except Exception as e:
	runner.check(False, "2.5 Terminal transition COMPLETED -> RUNNING", f"Wrong error: {type(e)}")

# Test 2.6: Terminal state mutation: COMPLETED -> FAILED
try:
	fsm.transition(JobStatus.FAILED)
	runner.check(False, "2.6 Terminal transition COMPLETED -> FAILED should fail")
except TerminalStateError:
	runner.check(True, "2.6 Terminal transition COMPLETED -> FAILED raises TerminalStateError")
except Exception as e:
	runner.check(False, "2.6 Terminal transition COMPLETED -> FAILED", f"Wrong error: {type(e)}")

# Test 2.7: Terminal state mutation: FAILED -> COMPLETED
spec_fail = JobSpec(job_id="job-fsm-fail", job_type="test")
fsm_fail = JobStateMachine(spec_fail)
fsm_fail.transition(JobStatus.RUNNING)
fsm_fail.record_result(JobResult(job_id="job-fsm-fail", status=JobStatus.FAILED))
try:
	fsm_fail.transition(JobStatus.COMPLETED)
	runner.check(False, "2.7 Terminal transition FAILED -> COMPLETED should fail")
except TerminalStateError:
	runner.check(True, "2.7 Terminal transition FAILED -> COMPLETED raises TerminalStateError")
except Exception as e:
	runner.check(False, "2.7 Terminal transition FAILED -> COMPLETED", f"Wrong error: {type(e)}")

# Test 2.8: Progress recording on terminal state raises TerminalStateError
try:
	prog = JobProgress(job_id="job-fsm-001", status=JobStatus.RUNNING, progress_pct=99.0)
	fsm.record_progress(prog)
	runner.check(False, "2.8 Progress on terminal state should fail")
except TerminalStateError:
	runner.check(True, "2.8 Progress on terminal state raises TerminalStateError")
except Exception as e:
	runner.check(False, "2.8 Progress on terminal state", f"Wrong error: {type(e)}")

# Test 2.9: Direct jump SUBMITTED -> COMPLETED rejected
spec_sub = JobSpec(job_id="job-fsm-sub", job_type="test")
fsm_sub = JobStateMachine(spec_sub)
try:
	fsm_sub.record_result(JobResult(job_id="job-fsm-sub", status=JobStatus.COMPLETED))
	runner.check(False, "2.9 Direct jump SUBMITTED -> COMPLETED should fail")
except InvalidStateTransitionError:
	runner.check(
		True, "2.9 Direct jump SUBMITTED -> COMPLETED raises InvalidStateTransitionError"
	)
except Exception as e:
	runner.check(False, "2.9 Direct jump SUBMITTED -> COMPLETED", f"Wrong error: {type(e)}")

# Test 2.10: ATOMICITY / LEAKAGE OF GENERATION ON REJECTED TRANSITIONS
# Adversarial question: If a transition on terminal FSM is rejected, does _generation leak/change?
spec_atom = JobSpec(job_id="job-fsm-atom", job_type="test", generation=1)
fsm_atom = JobStateMachine(spec_atom)
fsm_atom.transition(JobStatus.RUNNING)
fsm_atom.record_result(JobResult(job_id="job-fsm-atom", status=JobStatus.COMPLETED, generation=1))
initial_gen = fsm_atom.generation

# Attempt transition with higher generation on terminal state machine:
try:
	fsm_atom.transition(JobStatus.RUNNING, generation=10)
except TerminalStateError:
	pass

gen_after_rejected_transition = fsm_atom.generation
if gen_after_rejected_transition != initial_gen:
	runner.check(
		False,
		"2.10 Generation atomicity on rejected transition",
		f"BUG: generation changed from {initial_gen} to {gen_after_rejected_transition} "
		"despite TerminalStateError! Generation state was modified before terminal check.",
	)
else:
	runner.check(
		True, "2.10 Generation atomicity preserved on rejected transition (no state leakage)"
	)

# Also check record_progress generation leakage on terminal state machine:
try:
	fsm_atom.record_progress(
		JobProgress(job_id="job-fsm-atom", status=JobStatus.RUNNING, generation=20)
	)
except TerminalStateError:
	pass

gen_after_rejected_progress = fsm_atom.generation
if gen_after_rejected_progress != initial_gen:
	runner.check(
		False,
		"2.10b Generation atomicity on rejected progress",
		f"BUG: generation changed from {initial_gen} to {gen_after_rejected_progress} "
		"despite TerminalStateError! Generation state was modified before terminal check.",
	)
else:
	runner.check(
		True, "2.10b Generation atomicity preserved on rejected progress (no state leakage)"
	)

# Also check SessionStateMachine generation leakage on terminal state machine:
sess_atom = SessionConfig(session_id="sess-atom-1", modality=ModalityType.OCR, generation=1)
sess_fsm_atom = SessionStateMachine(sess_atom)
sess_fsm_atom.transition(SessionState.CONFIGURING)
sess_fsm_atom.transition(SessionState.ERROR)  # Terminal state
sess_initial_gen = sess_fsm_atom.generation

try:
	sess_fsm_atom.transition(SessionState.READY, generation=15)
except TerminalStateError:
	pass

sess_gen_after = sess_fsm_atom.generation
if sess_gen_after != sess_initial_gen:
	runner.check(
		False,
		"2.10c SessionStateMachine generation atomicity on rejected transition",
		f"BUG: session generation changed from {sess_initial_gen} to {sess_gen_after} "
		"despite TerminalStateError! Generation state was modified before terminal check.",
	)
else:
	runner.check(
		True,
		"2.10c SessionStateMachine generation atomicity preserved on rejected transition",
	)

# Also check JobStateMachine.record_result generation leakage on invalid transition:
spec_res_atom = JobSpec(job_id="job-fsm-res-atom", job_type="test", generation=1)
fsm_res_atom = JobStateMachine(spec_res_atom)
res_initial_gen = fsm_res_atom.generation

try:
	# Attempt record_result COMPLETED directly from SUBMITTED (invalid transition) with higher generation:
	fsm_res_atom.record_result(
		JobResult(job_id="job-fsm-res-atom", status=JobStatus.COMPLETED, generation=12)
	)
except InvalidStateTransitionError:
	pass

res_gen_after = fsm_res_atom.generation
if res_gen_after != res_initial_gen:
	runner.check(
		False,
		"2.10d record_result generation atomicity on rejected transition",
		f"BUG: generation changed from {res_initial_gen} to {res_gen_after} "
		"despite InvalidStateTransitionError! Generation state was modified before validation check.",
	)
else:
	runner.check(
		True,
		"2.10d record_result generation atomicity preserved on rejected transition",
	)

# ===========================================================================
# CATEGORY 3: Single-Result Invariant & Multi-Terminal Contention
# ===========================================================================
print("\n=== Category 3: Single-Result Invariant ===")

# Test 3.1: Sequential second record_result rejected
spec_single = JobSpec(job_id="job-single-1", job_type="test")
fsm_single = JobStateMachine(spec_single)
fsm_single.transition(JobStatus.RUNNING)
res1 = JobResult(job_id="job-single-1", status=JobStatus.COMPLETED, result_data={"winner": 1})
res2 = JobResult(job_id="job-single-1", status=JobStatus.COMPLETED, result_data={"winner": 2})

fsm_single.record_result(res1)
try:
	fsm_single.record_result(res2)
	runner.check(False, "3.1 Second record_result should raise TerminalStateError")
except TerminalStateError:
	runner.check(True, "3.1 Second record_result raises TerminalStateError")
except Exception as e:
	runner.check(False, "3.1 Second record_result", f"Wrong error: {type(e)}")

runner.check(
	fsm_single.result is not None and fsm_single.result.result_data == {"winner": 1},
	"3.1b Single-result remains the first recorded result",
)

# Test 3.2: Concurrent race to record_result across 30 threads
spec_race = JobSpec(job_id="job-race-1", job_type="test")
fsm_race = JobStateMachine(spec_race)
fsm_race.transition(JobStatus.RUNNING)

winner_results: list[int] = []
terminal_errors: list[Exception] = []
other_errors: list[Exception] = []


def try_record(idx: int):
	try:
		r = JobResult(job_id="job-race-1", status=JobStatus.COMPLETED, result_data={"idx": idx})
		fsm_race.record_result(r)
		winner_results.append(idx)
	except TerminalStateError as err:
		terminal_errors.append(err)
	except Exception as err:
		other_errors.append(err)


threads = [threading.Thread(target=try_record, args=(i,)) for i in range(30)]
for t in threads:
	t.start()
for t in threads:
	t.join()

runner.check(
	len(winner_results) == 1 and len(terminal_errors) == 29 and len(other_errors) == 0,
	"3.2 Concurrent record_result contention: exactly 1 winner, 29 TerminalStateError",
	f"Winners: {len(winner_results)}, TerminalErrors: {len(terminal_errors)}, Other: {other_errors}",
)

# ===========================================================================
# CATEGORY 4: Concurrent Cancellation, Callbacks & Coordinator Deadlock Audit
# ===========================================================================
print("\n=== Category 4: Cancellation Concurrency & Deadlock Audit ===")

# Test 4.1: Concurrent cancel() across 50 threads
token = CancellationToken("job-cancel-test")
callback_counts = [0]


def on_cancel():
	callback_counts[0] += 1


token.register_callback(on_cancel)

threads = [
	threading.Thread(target=token.cancel, args=(f"thread-{i}",)) for i in range(50)
]
for t in threads:
	t.start()
for t in threads:
	t.join()

runner.check(
	token.is_cancelled and callback_counts[0] == 1,
	"4.1 50 concurrent cancel() calls: is_cancelled=True, callback fired exactly once",
	f"callback_counts: {callback_counts[0]}",
)

# Test 4.2: Callback throwing exception does not disrupt cancel() or other callbacks
token2 = CancellationToken("job-cancel-err")
fired = []


def bad_cb():
	fired.append("bad")
	raise RuntimeError("Kaboom from callback")


def good_cb():
	fired.append("good")


token2.register_callback(bad_cb)
token2.register_callback(good_cb)

try:
	token2.cancel("testing_exceptions")
	runner.check(
		token2.is_cancelled and fired == ["bad", "good"],
		"4.2 Callback exception safely suppressed without disrupting subsequent callbacks",
		f"fired: {fired}",
	)
except Exception as e:
	runner.check(False, "4.2 Callback exception handling", str(e))

# Test 4.3: Callback registering another callback does not deadlock
token3 = CancellationToken("job-cancel-nested")
nested_fired = []


def outer_cb():
	nested_fired.append("outer")
	token3.register_callback(lambda: nested_fired.append("nested"))


token3.register_callback(outer_cb)
token3.cancel("testing_nested")
runner.check(
	nested_fired == ["outer", "nested"],
	"4.3 Nested callback registration during cancellation executes safely",
	f"nested_fired: {nested_fired}",
)

# Test 4.4: ADVERSARIAL RE-ENTRANCY DEADLOCK AUDIT ON CancellationCoordinator
# In cancellation.py:
# request_cancellation holds self._lock while calling token.cancel().
# If a callback calls any coordinator method that also acquires self._lock,
# a non-reentrant Lock will cause an immediate DEADLOCK.
coord = CancellationCoordinator()
tok = coord.register_token("job-deadlock-audit")

deadlock_detected = False
lock_acquired_in_cb = False


def reentrant_callback():
	global lock_acquired_in_cb
	# This callback queries the coordinator while request_cancellation is running!
	# Both methods need coord._lock.
	tok_ref = coord.get_token("job-deadlock-audit")
	if tok_ref is not None:
		lock_acquired_in_cb = True


tok.register_callback(reentrant_callback)


def run_request():
	global deadlock_detected
	coord.request_cancellation("job-deadlock-audit")


t = threading.Thread(target=run_request, daemon=True)
t.start()
t.join(timeout=0.5)  # Wait up to 0.5s

if t.is_alive():
	deadlock_detected = True
	runner.check(
		False,
		"4.4 CancellationCoordinator re-entrancy deadlock audit",
		"CRITICAL DEADLOCK DETECTED! CancellationCoordinator.request_cancellation holds "
		"non-reentrant Lock while invoking token.cancel(), causing permanent deadlock when "
		"a cancellation callback queries the coordinator (e.g. get_token, unregister_token, is_preemption_due).",
	)
else:
	runner.check(
		True,
		"4.4 CancellationCoordinator re-entrancy deadlock audit passed (no deadlock)",
	)

# ===========================================================================
# CATEGORY 5: Stale Generation Fencing
# ===========================================================================
print("\n=== Category 5: Stale Generation Fencing ===")

spec_fence = JobSpec(job_id="job-fence-1", job_type="test", generation=5)
fsm_fence = JobStateMachine(spec_fence)

# Test 5.1: Transition with stale generation rejected
try:
	fsm_fence.transition(JobStatus.RUNNING, generation=4)
	runner.check(False, "5.1 Stale transition generation (4 < 5) should fail")
except InvalidStateTransitionError:
	runner.check(True, "5.1 Stale transition generation (4 < 5) raises InvalidStateTransitionError")
except Exception as e:
	runner.check(False, "5.1 Stale transition generation", f"Wrong error: {type(e)}")

# Test 5.2: Transition with equal generation accepted
try:
	fsm_fence.transition(JobStatus.RUNNING, generation=5)
	runner.check(
		fsm_fence.state == JobStatus.RUNNING and fsm_fence.generation == 5,
		"5.2 Equal generation transition accepted",
	)
except Exception as e:
	runner.check(False, "5.2 Equal generation transition", str(e))

# Test 5.3: Transition with higher generation accepted and advances generation
try:
	fsm_fence.transition(JobStatus.RUNNING, generation=6)
	runner.check(
		fsm_fence.generation == 6,
		"5.3 Higher generation transition (6 > 5) advances active generation",
	)
except Exception as e:
	runner.check(False, "5.3 Higher generation transition", str(e))

# Test 5.4: Stale progress generation rejected
try:
	stale_prog = JobProgress(
		job_id="job-fence-1", status=JobStatus.RUNNING, progress_pct=10.0, generation=5
	)
	fsm_fence.record_progress(stale_prog)
	runner.check(False, "5.4 Stale progress generation (5 < 6) should fail")
except InvalidStateTransitionError:
	runner.check(True, "5.4 Stale progress generation (5 < 6) raises InvalidStateTransitionError")
except Exception as e:
	runner.check(False, "5.4 Stale progress generation", f"Wrong error: {type(e)}")

# Test 5.5: Stale result generation rejected
try:
	stale_res = JobResult(job_id="job-fence-1", status=JobStatus.COMPLETED, generation=5)
	fsm_fence.record_result(stale_res)
	runner.check(False, "5.5 Stale result generation (5 < 6) should fail")
except InvalidStateTransitionError:
	runner.check(True, "5.5 Stale result generation (5 < 6) raises InvalidStateTransitionError")
except Exception as e:
	runner.check(False, "5.5 Stale result generation", f"Wrong error: {type(e)}")

# Test 5.6: SessionStateMachine stale generation rejection
s_cfg = SessionConfig(
	session_id="sess-fence-1", modality=ModalityType.OCR, generation=3
)
s_fsm = SessionStateMachine(s_cfg)
try:
	s_fsm.transition(SessionState.CONFIGURING, generation=2)
	runner.check(False, "5.6 Session FSM stale generation (2 < 3) should fail")
except InvalidStateTransitionError:
	runner.check(
		True, "5.6 Session FSM stale generation (2 < 3) raises InvalidStateTransitionError"
	)
except Exception as e:
	runner.check(False, "5.6 Session FSM stale generation", f"Wrong error: {type(e)}")

# ===========================================================================
# CATEGORY 6: Protocol & Framing Adversarial Injection
# ===========================================================================
print("\n=== Category 6: Protocol Framing Adversarial Injection ===")

# Test 6.1: Corrupt magic bytes in binary frame
bad_magic_frame = b"\x00\x00\x00\x00\x00\x00\x00\x02\x00\x00\x00\x00{}"
try:
	decode_binary_frame(bad_magic_frame)
	runner.check(False, "6.1 Corrupt magic bytes should fail")
except ProtocolError as pe:
	runner.check(
		pe.error_code == ErrorCode.INVALID_FRAME,
		"6.1 Corrupt magic bytes raises ProtocolError(INVALID_FRAME)",
		str(pe),
	)
except Exception as e:
	runner.check(False, "6.1 Corrupt magic bytes", f"Wrong error: {type(e)}")

# Test 6.2: Binary frame length header mismatch
lying_frame = b"\xAA\x55\x01\x00\x00\x00\x00\x10\x00\x00\x00\x10short"
try:
	decode_binary_frame(lying_frame)
	runner.check(False, "6.2 Lying binary frame length header should fail")
except ProtocolError as pe:
	runner.check(
		pe.error_code == ErrorCode.INVALID_FRAME,
		"6.2 Lying binary frame length header raises ProtocolError(INVALID_FRAME)",
		str(pe),
	)
except Exception as e:
	runner.check(False, "6.2 Lying binary frame length header", f"Wrong error: {type(e)}")

# Test 6.3: Binary frame smaller than 12-byte header
try:
	decode_binary_frame(b"\xAA\x55\x01")
	runner.check(False, "6.3 Binary frame < 12 bytes should fail")
except ProtocolError as pe:
	runner.check(
		pe.error_code == ErrorCode.INVALID_FRAME,
		"6.3 Binary frame < 12 bytes raises ProtocolError(INVALID_FRAME)",
	)
except Exception as e:
	runner.check(False, "6.3 Binary frame < 12 bytes", f"Wrong error: {type(e)}")

# Test 6.4: NDJSON frame exceeding 16 MB limit
huge_payload = "a" * (MAX_FRAME_SIZE + 10)
try:
	encode_ndjson_frame(huge_payload)
	runner.check(False, "6.4 Oversized NDJSON encode should fail")
except ProtocolError as pe:
	runner.check(
		pe.error_code == ErrorCode.FRAME_TOO_LARGE,
		"6.4 Oversized NDJSON encode raises ProtocolError(FRAME_TOO_LARGE)",
	)
except Exception as e:
	runner.check(False, "6.4 Oversized NDJSON encode", f"Wrong error: {type(e)}")

# Test 6.5: Empty NDJSON decode
try:
	decode_ndjson_frame(b"   \n  \r\n")
	runner.check(False, "6.5 Empty whitespace NDJSON should fail")
except ProtocolError as pe:
	runner.check(
		pe.error_code == ErrorCode.INVALID_FRAME,
		"6.5 Empty whitespace NDJSON raises ProtocolError(INVALID_FRAME)",
	)
except Exception as e:
	runner.check(False, "6.5 Empty whitespace NDJSON", f"Wrong error: {type(e)}")

# Test 6.6: Handshake negotiation with major version mismatch
handshake_req = HandshakeRequest(protocol_version="2.0.0")
handshake_resp = validate_handshake(handshake_req, worker_version="1.0.0")
runner.check(
	not handshake_resp.accepted and "Incompatible" in (handshake_resp.error_message or ""),
	"6.6 Handshake major version mismatch rejected (accepted=False)",
	f"Response: {handshake_resp}",
)

# Test 6.7: Malformed version strings in is_protocol_compatible
runner.check(
	not is_protocol_compatible("", "1.0.0")
	and not is_protocol_compatible("abc", "1.0.0")
	and not is_protocol_compatible("2", "1"),
	"6.7 Malformed SemVer strings safely return False without exception",
)

# ===========================================================================
# CATEGORY 7: Schema Validation Adversarial Fuzzing
# ===========================================================================
print("\n=== Category 7: Schema Validation Adversarial Fuzzing ===")

# Test 7.1: Type confusion: boolean passed for integer field
spec_dict_bool = {
	"type": "job_submission",
	"job_id": "job-type-confuse",
	"job_type": "compute",
	"payload": {},
	"priority": True,  # Boolean where integer expected!
	"timeout_seconds": 300.0,
	"generation": 1,
	"created_at_epoch_ms": 1000,
}
try:
	validate_schema(spec_dict_bool, JOB_SPEC_SCHEMA)
	runner.check(False, "7.1 Boolean passed for integer should fail schema validation")
except ValidationError as ve:
	runner.check(
		"expected type 'integer', got 'bool'" in str(ve),
		"7.1 Boolean passed for integer caught by validator (integer != bool distinction)",
		str(ve),
	)
except Exception as e:
	runner.check(False, "7.1 Boolean passed for integer", f"Wrong error: {type(e)}")

# Test 7.2: Float passed for integer field
spec_dict_float = dict(spec_dict_bool)
spec_dict_float["priority"] = 10
spec_dict_float["generation"] = 1.5  # Float where integer expected!
try:
	validate_schema(spec_dict_float, JOB_SPEC_SCHEMA)
	runner.check(False, "7.2 Float passed for integer should fail schema validation")
except ValidationError:
	runner.check(True, "7.2 Float passed for integer rejected by validator")
except Exception as e:
	runner.check(False, "7.2 Float passed for integer", f"Wrong error: {type(e)}")

# Test 7.3: Out-of-bounds number: progress_pct > 100.0
prog_dict_oob = {
	"type": "job_update",
	"job_id": "job-prog-oob",
	"status": "running",
	"progress_pct": 105.0,  # exceeds maximum 100.0
	"status_message": "Over 100%",
	"bytes_completed": 105,
	"bytes_total": 100,
	"throughput_bytes_per_sec": 10.0,
	"eta_seconds": 0.0,
	"generation": 1,
	"timestamp_epoch_ms": 1000,
}
try:
	validate_schema(prog_dict_oob, JOB_PROGRESS_SCHEMA)
	runner.check(False, "7.3 progress_pct > 100 should fail schema validation")
except ValidationError as ve:
	runner.check(
		"greater than maximum 100.0" in str(ve),
		"7.3 progress_pct > 100.0 rejected with maximum range check",
		str(ve),
	)
except Exception as e:
	runner.check(False, "7.3 progress_pct > 100", f"Wrong error: {type(e)}")

# Test 7.4: Schema poisoning: unexpected additional property on additionalProperties: False
spec_dict_poison = dict(spec_dict_bool)
spec_dict_poison["priority"] = 10
spec_dict_poison["injected_backdoor_field"] = "exploit"
try:
	validate_schema(spec_dict_poison, JOB_SPEC_SCHEMA)
	runner.check(False, "7.4 Injected additional property should fail schema validation")
except ValidationError as ve:
	runner.check(
		"unexpected additional property" in str(ve),
		"7.4 Injected additional property rejected by additionalProperties: False",
		str(ve),
	)
except Exception as e:
	runner.check(False, "7.4 Injected additional property", f"Wrong error: {type(e)}")

# Test 7.5: Const type mismatch
spec_dict_bad_type = dict(spec_dict_bool)
spec_dict_bad_type["priority"] = 10
spec_dict_bad_type["type"] = "malicious_type"
try:
	validate_schema(spec_dict_bad_type, JOB_SPEC_SCHEMA)
	runner.check(False, "7.5 Const mismatch should fail schema validation")
except ValidationError as ve:
	runner.check(
		"expected const 'job_submission'" in str(ve),
		"7.5 Const mismatch rejected by validator",
		str(ve),
	)
except Exception as e:
	runner.check(False, "7.5 Const mismatch", f"Wrong error: {type(e)}")

# ===========================================================================
# SUMMARY
# ===========================================================================
print("\n" + "=" * 60)
print(f"ADVERSARIAL SUITE SUMMARY: {runner.passed} PASSED, {runner.failed} FAILED")
print("=" * 60)

if runner.failed > 0:
	print("\nFAILURES / FINDINGS:")
	for f in runner.findings:
		print(f)
	sys.exit(1)
else:
	print("\nALL ADVERSARIAL TESTS PASSED CLEANLY!")
	if runner.findings:
		print("\nOBSERVATIONS / DESIGN FINDINGS:")
		for f in runner.findings:
			print(f)
	sys.exit(0)
