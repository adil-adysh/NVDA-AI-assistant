#!/usr/bin/env python3
"""Adversarial Verification Suite for Schema and Protocol Hardening.

Milestone 1 (Slice 2) Iteration 2
Author: Challenger 2
Tests:
  1. validate_schema numeric range checks strictly reject NaN, Inf, -Inf
  2. decode_ndjson_frame strictly rejects non-dict JSON payloads
  3. decode_binary_frame strictly rejects non-dict JSON metadata
  4. Fuzz testing across primitive permutations and boundary conditions
  5. Regression safety for state machine generation and cancellation re-entrancy
"""

import math
import struct
import sys
import threading
import time
from pathlib import Path
from typing import Any

# Ensure addon path is in sys.path
ADDON_DIR = Path(__file__).resolve().parents[3] / "addon" / "globalPlugins" / "AI-assistant"
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from core.job.cancellation import CancellationCoordinator, CancellationToken
from core.job.dto import (
    HandshakeRequest,
    JobFailure,
    JobProgress,
    JobResult,
    JobSnapshot,
    JobSpec,
    JobState,
    JobStatus,
    SessionConfig,
    StreamChunk,
    WorkerHealth,
)
from core.job.protocol import (
    HEADER_SIZE,
    MAGIC,
    MAX_FRAME_SIZE,
    ErrorCode,
    ProtocolError,
    decode_binary_frame,
    decode_ndjson_frame,
    encode_binary_frame,
    encode_ndjson_frame,
)
from core.job.schemas import (
    HANDSHAKE_REQUEST_SCHEMA,
    JOB_PROGRESS_SCHEMA,
    JOB_RESULT_SCHEMA,
    JOB_SPEC_SCHEMA,
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

passed_count = 0
failed_count = 0


def record_result(test_id: str, desc: str, passed: bool, detail: str = "") -> None:
    global passed_count, failed_count
    if passed:
        passed_count += 1
        print(f"  [PASS] {test_id}: {desc}")
    else:
        failed_count += 1
        print(f"  [FAIL] {test_id}: {desc} -- {detail}")


# ===========================================================================
# Section 1: Schema Numeric Range Checks (NaN, Inf, -Inf Rejection)
# ===========================================================================

print("\n--- SECTION 1: Schema Numeric Range Checks ---")

# 1.1: JOB_PROGRESS_SCHEMA progress_pct with NaN, Inf, -Inf
for val, label in [(float("nan"), "NaN"), (float("inf"), "Inf"), (float("-inf"), "-Inf")]:
    p = JobProgress(job_id="j1", status=JobStatus.RUNNING).to_dict()
    p["progress_pct"] = val
    try:
        validate_schema(p, JOB_PROGRESS_SCHEMA)
        record_result(f"1.1_{label}", f"JOB_PROGRESS_SCHEMA rejects progress_pct={label}", False, "Validation unexpectedly succeeded!")
    except ValidationError as exc:
        msg = str(exc)
        is_correct = "non-finite number" in msg
        record_result(f"1.1_{label}", f"JOB_PROGRESS_SCHEMA rejects progress_pct={label}", is_correct, f"Error: {msg}")
    except Exception as exc:
        record_result(f"1.1_{label}", f"JOB_PROGRESS_SCHEMA rejects progress_pct={label}", False, f"Unexpected error type: {type(exc).__name__}: {exc}")

# 1.2: JOB_PROGRESS_SCHEMA throughput_bytes_per_sec with NaN, Inf, -Inf
for val, label in [(float("nan"), "NaN"), (float("inf"), "Inf"), (float("-inf"), "-Inf")]:
    p = JobProgress(job_id="j1", status=JobStatus.RUNNING).to_dict()
    p["throughput_bytes_per_sec"] = val
    try:
        validate_schema(p, JOB_PROGRESS_SCHEMA)
        record_result(f"1.2_{label}", f"JOB_PROGRESS_SCHEMA rejects throughput={label}", False, "Validation unexpectedly succeeded!")
    except ValidationError as exc:
        record_result(f"1.2_{label}", f"JOB_PROGRESS_SCHEMA rejects throughput={label}", "non-finite number" in str(exc), str(exc))

# 1.3: JOB_PROGRESS_SCHEMA eta_seconds with NaN, Inf, -Inf
for val, label in [(float("nan"), "NaN"), (float("inf"), "Inf"), (float("-inf"), "-Inf")]:
    p = JobProgress(job_id="j1", status=JobStatus.RUNNING).to_dict()
    p["eta_seconds"] = val
    try:
        validate_schema(p, JOB_PROGRESS_SCHEMA)
        record_result(f"1.3_{label}", f"JOB_PROGRESS_SCHEMA rejects eta_seconds={label}", False, "Validation unexpectedly succeeded!")
    except ValidationError as exc:
        record_result(f"1.3_{label}", f"JOB_PROGRESS_SCHEMA rejects eta_seconds={label}", "non-finite number" in str(exc), str(exc))

# 1.4: JOB_SPEC_SCHEMA timeout_seconds with NaN, Inf, -Inf
for val, label in [(float("nan"), "NaN"), (float("inf"), "Inf"), (float("-inf"), "-Inf")]:
    s = JobSpec(job_id="j1", job_type="inference").to_dict()
    s["timeout_seconds"] = val
    try:
        validate_schema(s, JOB_SPEC_SCHEMA)
        record_result(f"1.4_{label}", f"JOB_SPEC_SCHEMA rejects timeout_seconds={label}", False, "Validation unexpectedly succeeded!")
    except ValidationError as exc:
        record_result(f"1.4_{label}", f"JOB_SPEC_SCHEMA rejects timeout_seconds={label}", "non-finite number" in str(exc), str(exc))

# 1.5: STREAM_CHUNK_SCHEMA confidence with NaN, Inf, -Inf
for val, label in [(float("nan"), "NaN"), (float("inf"), "Inf"), (float("-inf"), "-Inf")]:
    chunk = StreamChunk(session_id="s1", sequence_number=0, is_partial=False, payload_text="hello").to_dict()
    chunk["confidence"] = val
    try:
        validate_schema(chunk, STREAM_CHUNK_SCHEMA)
        record_result(f"1.5_{label}", f"STREAM_CHUNK_SCHEMA rejects confidence={label}", False, "Validation unexpectedly succeeded!")
    except ValidationError as exc:
        record_result(f"1.5_{label}", f"STREAM_CHUNK_SCHEMA rejects confidence={label}", "non-finite number" in str(exc), str(exc))

# 1.6: WORKER_HEALTH_SCHEMA uptime_seconds & cpu_percent with NaN, Inf, -Inf
for val, label in [(float("nan"), "NaN"), (float("inf"), "Inf"), (float("-inf"), "-Inf")]:
    wh = WorkerHealth(
        worker_pid=100,
        generation=1,
        uptime_seconds=10.0,
        active_jobs_count=0,
        active_sessions_count=0,
        cpu_percent=1.0,
        rss_memory_bytes=1000,
    ).to_dict()
    wh["uptime_seconds"] = val
    try:
        validate_schema(wh, WORKER_HEALTH_SCHEMA)
        record_result(f"1.6a_{label}", f"WORKER_HEALTH_SCHEMA rejects uptime_seconds={label}", False, "Validation unexpectedly succeeded!")
    except ValidationError as exc:
        record_result(f"1.6a_{label}", f"WORKER_HEALTH_SCHEMA rejects uptime_seconds={label}", "non-finite number" in str(exc), str(exc))

    wh2 = WorkerHealth(
        worker_pid=100,
        generation=1,
        uptime_seconds=10.0,
        active_jobs_count=0,
        active_sessions_count=0,
        cpu_percent=1.0,
        rss_memory_bytes=1000,
    ).to_dict()
    wh2["cpu_percent"] = val
    try:
        validate_schema(wh2, WORKER_HEALTH_SCHEMA)
        record_result(f"1.6b_{label}", f"WORKER_HEALTH_SCHEMA rejects cpu_percent={label}", False, "Validation unexpectedly succeeded!")
    except ValidationError as exc:
        record_result(f"1.6b_{label}", f"WORKER_HEALTH_SCHEMA rejects cpu_percent={label}", "non-finite number" in str(exc), str(exc))

# 1.7: Custom schema with exclusiveMinimum
schema_excl_min = {
    "type": "object",
    "properties": {"val": {"type": "number", "exclusiveMinimum": 0.0}},
}
for val, label in [(float("nan"), "NaN"), (float("inf"), "Inf"), (float("-inf"), "-Inf")]:
    try:
        validate_schema({"val": val}, schema_excl_min)
        record_result(f"1.7_{label}", f"exclusiveMinimum rejects {label}", False, "Validation unexpectedly succeeded!")
    except ValidationError as exc:
        record_result(f"1.7_{label}", f"exclusiveMinimum rejects {label}", "non-finite number" in str(exc), str(exc))

# 1.8: Custom schema with exclusiveMaximum
schema_excl_max = {
    "type": "object",
    "properties": {"val": {"type": "number", "exclusiveMaximum": 100.0}},
}
for val, label in [(float("nan"), "NaN"), (float("inf"), "Inf"), (float("-inf"), "-Inf")]:
    try:
        validate_schema({"val": val}, schema_excl_max)
        record_result(f"1.8_{label}", f"exclusiveMaximum rejects {label}", False, "Validation unexpectedly succeeded!")
    except ValidationError as exc:
        record_result(f"1.8_{label}", f"exclusiveMaximum rejects {label}", "non-finite number" in str(exc), str(exc))

# 1.9: Array items with numeric range checks containing NaN
schema_array = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "array",
            "items": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        }
    },
}
try:
    validate_schema({"scores": [0.5, float("nan"), 0.9]}, schema_array)
    record_result("1.9", "Array items reject NaN", False, "Validation unexpectedly succeeded!")
except ValidationError as exc:
    record_result("1.9", "Array items reject NaN", "non-finite number" in str(exc), str(exc))

# 1.10: Valid numeric values pass cleanly
valid_samples = [
    0.0, 0, 1, 50.0, 100.0, 0.0001, 99.9999
]
all_valid = True
for v in valid_samples:
    p = JobProgress(job_id="j1", status=JobStatus.RUNNING).to_dict()
    p["progress_pct"] = v
    try:
        validate_schema(p, JOB_PROGRESS_SCHEMA)
    except Exception as exc:
        all_valid = False
        record_result("1.10", f"Valid progress_pct={v} must pass", False, str(exc))
        break
if all_valid:
    record_result("1.10", "All valid finite progress_pct values pass validation", True)


# ===========================================================================
# Section 2: NDJSON Non-Dict Rejection (decode_ndjson_frame)
# ===========================================================================

print("\n--- SECTION 2: NDJSON Non-Dict Rejection ---")

non_dict_ndjson_samples = [
    (b"42\n", "Integer 42"),
    (b"0\n", "Integer 0"),
    (b"-100\n", "Negative integer -100"),
    (b"3.14159\n", "Float 3.14159"),
    (b"-0.001\n", "Negative float"),
    (b"1e10\n", "Scientific float 1e10"),
    (b'"hello world"\n', "Double-quoted string"),
    (b'""\n', "Empty string"),
    (b"[1, 2, 3]\n", "List of integers"),
    (b"[]\n", "Empty list"),
    (b"['a', 'b']\n", "Single quoted string array (malformed or parsed)"),
    (b'[{"nested": "object"}]\n', "Array containing a dict"),
    (b"true\n", "Boolean true"),
    (b"false\n", "Boolean false"),
    (b"null\n", "Null primitive"),
    (b"   42   \r\n", "Padded integer with CRLF"),
    (b"   \"string\"   \n", "Padded string"),
    (b"   [1, 2]   \n", "Padded array"),
    (b"   true   \n", "Padded boolean"),
    (b"   null   \n", "Padded null"),
]

for idx, (raw_frame, desc) in enumerate(non_dict_ndjson_samples, start=1):
    test_id = f"2.{idx}"
    try:
        res = decode_ndjson_frame(raw_frame)
        record_result(test_id, f"decode_ndjson_frame rejects {desc}", False, f"Unexpectedly returned {type(res).__name__}: {res!r}")
    except ProtocolError as exc:
        is_correct = exc.error_code == ErrorCode.INVALID_FRAME and (
            "Frame payload must be a JSON object" in str(exc) or "Failed to parse NDJSON frame" in str(exc)
        )
        record_result(test_id, f"decode_ndjson_frame rejects {desc}", is_correct, f"Error: code={exc.error_code}, msg={exc}")
    except Exception as exc:
        record_result(test_id, f"decode_ndjson_frame rejects {desc}", False, f"Unexpected error {type(exc).__name__}: {exc}")

# 2.21: Valid dictionary frames must pass cleanly
valid_dict_samples = [
    b"{}\n",
    b'{"status": "ok"}\n',
    b'{"nested": {"count": 10}, "list": [1, 2, 3]}\n',
]
for idx, raw_frame in enumerate(valid_dict_samples, start=21):
    test_id = f"2.{idx}"
    try:
        decoded = decode_ndjson_frame(raw_frame)
        record_result(test_id, f"Valid dict {raw_frame.strip()!r} decoded as dict", isinstance(decoded, dict))
    except Exception as exc:
        record_result(test_id, f"Valid dict {raw_frame.strip()!r} decoded as dict", False, str(exc))


# ===========================================================================
# Section 3: Hybrid Binary Framing Non-Dict Rejection (decode_binary_frame)
# ===========================================================================

print("\n--- SECTION 3: Binary Frame Non-Dict Rejection ---")

non_dict_meta_samples = [
    (b"42", "Integer 42"),
    (b"0", "Integer 0"),
    (b"-50", "Negative integer -50"),
    (b"3.14159", "Float 3.14159"),
    (b'"sample metadata string"', "String metadata"),
    (b'""', "Empty string metadata"),
    (b"[1, 2, 3]", "List metadata"),
    (b"[]", "Empty list metadata"),
    (b'[{"inner": "dict"}]', "List of dicts"),
    (b"true", "Boolean true"),
    (b"false", "Boolean false"),
    (b"null", "Null metadata"),
]

for idx, (raw_meta, desc) in enumerate(non_dict_meta_samples, start=1):
    test_id = f"3.{idx}"
    bin_payload = b"raw_binary_bytes_12345"
    header = struct.pack(">4sII", MAGIC, len(raw_meta), len(bin_payload))
    frame = header + raw_meta + bin_payload
    try:
        meta_out, bin_out = decode_binary_frame(frame)
        record_result(test_id, f"decode_binary_frame rejects {desc}", False, f"Unexpectedly returned meta={meta_out!r}")
    except ProtocolError as exc:
        is_correct = exc.error_code == ErrorCode.INVALID_FRAME and "Frame payload must be a JSON object" in str(exc)
        record_result(test_id, f"decode_binary_frame rejects {desc}", is_correct, f"Error: code={exc.error_code}, msg={exc}")
    except Exception as exc:
        record_result(test_id, f"decode_binary_frame rejects {desc}", False, f"Unexpected error {type(exc).__name__}: {exc}")

# 3.13: Valid dictionary metadata passes cleanly
test_id = "3.13"
valid_meta = {"session_id": "test_sess_01", "chunk_index": 7}
valid_bin = b"\xde\xad\xbe\xef"
enc_frame = encode_binary_frame(valid_meta, valid_bin)
try:
    dec_meta, dec_bin = decode_binary_frame(enc_frame)
    ok = (dec_meta == valid_meta and dec_bin == valid_bin)
    record_result(test_id, "Valid binary frame with dict metadata passes", ok)
except Exception as exc:
    record_result(test_id, "Valid binary frame with dict metadata passes", False, str(exc))

# 3.14: Empty dict metadata passes cleanly
test_id = "3.14"
enc_frame_empty = encode_binary_frame({}, b"")
try:
    dec_meta, dec_bin = decode_binary_frame(enc_frame_empty)
    ok = (dec_meta == {} and dec_bin == b"")
    record_result(test_id, "Empty dict binary frame passes", ok)
except Exception as exc:
    record_result(test_id, "Empty dict binary frame passes", False, str(exc))


# ===========================================================================
# Section 4: Fuzzing & High-Volume Permutations
# ===========================================================================

print("\n--- SECTION 4: High-Volume Fuzzing & Permutations ---")

fuzz_primitives = [
    "0", "1", "-1", "99999999999999999999", "3.14159", "-2.718", "1e-10", "1e+20",
    '"a"', '""', '"hello \\"world\\""', '"[1, 2, 3]"',
    "[]", "[1]", "[1, 2, 3]", '["a", "b"]', '[true, false, null]', '[[1], [2]]',
    "true", "false", "null"
]

ndjson_fuzz_success = True
for prim in fuzz_primitives:
    raw = (prim + "\n").encode("utf-8")
    try:
        res = decode_ndjson_frame(raw)
        ndjson_fuzz_success = False
        print(f"    Fuzz NDJSON failure on: {prim!r} -> returned {res!r}")
        break
    except ProtocolError as exc:
        if exc.error_code != ErrorCode.INVALID_FRAME:
            ndjson_fuzz_success = False
            print(f"    Fuzz NDJSON wrong error code on: {prim!r} -> {exc.error_code}")
            break
    except Exception as exc:
        ndjson_fuzz_success = False
        print(f"    Fuzz NDJSON unexpected exception on: {prim!r} -> {exc}")
        break

record_result("4.1", f"Fuzzed {len(fuzz_primitives)} non-dict NDJSON payloads strictly rejected", ndjson_fuzz_success)

bin_fuzz_success = True
for prim in fuzz_primitives:
    raw_meta = prim.encode("utf-8")
    header = struct.pack(">4sII", MAGIC, len(raw_meta), 4)
    frame = header + raw_meta + b"test"
    try:
        res, _ = decode_binary_frame(frame)
        bin_fuzz_success = False
        print(f"    Fuzz binary failure on: {prim!r} -> returned {res!r}")
        break
    except ProtocolError as exc:
        if exc.error_code != ErrorCode.INVALID_FRAME:
            bin_fuzz_success = False
            print(f"    Fuzz binary wrong error code on: {prim!r} -> {exc.error_code}")
            break
    except Exception as exc:
        bin_fuzz_success = False
        print(f"    Fuzz binary unexpected exception on: {prim!r} -> {exc}")
        break

record_result("4.2", f"Fuzzed {len(fuzz_primitives)} non-dict binary metadata payloads strictly rejected", bin_fuzz_success)

# 4.3: NDJSON payloads without trailing newlines
no_newline_samples = [(b"123", "raw int without newline"), (b'"hello"', "raw string without newline"), (b"[1, 2]", "raw array without newline")]
no_newline_ok = True
for raw, label in no_newline_samples:
    try:
        decode_ndjson_frame(raw)
        no_newline_ok = False
        record_result(f"4.3_{label}", f"decode_ndjson_frame rejects {label}", False, "Unexpectedly accepted")
    except ProtocolError as exc:
        record_result(f"4.3_{label}", f"decode_ndjson_frame rejects {label}", exc.error_code == ErrorCode.INVALID_FRAME)

# 4.4: Binary frame with empty metadata (meta_len = 0)
zero_meta_header = struct.pack(">4sII", MAGIC, 0, 4) + b"data"
try:
    decode_binary_frame(zero_meta_header)
    record_result("4.4", "Binary frame with zero meta_len rejected", False, "Unexpectedly accepted")
except ProtocolError as exc:
    record_result("4.4", "Binary frame with zero meta_len rejected", exc.error_code == ErrorCode.INVALID_FRAME)

# 4.5: Multiple simultaneous NaN/Inf fields in a single DTO
multi_nan_progress = JobProgress(job_id="j1", status=JobStatus.RUNNING).to_dict()
multi_nan_progress["progress_pct"] = float("nan")
multi_nan_progress["throughput_bytes_per_sec"] = float("inf")
multi_nan_progress["eta_seconds"] = float("-inf")
try:
    validate_schema(multi_nan_progress, JOB_PROGRESS_SCHEMA)
    record_result("4.5", "Multi-NaN/Inf fields rejected simultaneously", False, "Unexpectedly accepted")
except ValidationError as exc:
    err_count = sum(1 for e in exc.errors if "non-finite number" in e)
    record_result("4.5", f"Multi-NaN/Inf fields rejected simultaneously (found {err_count} errors)", err_count >= 3, str(exc))

# 4.6: Negative range schema with Inf and -Inf
neg_range_schema = {
    "type": "object",
    "properties": {"val": {"type": "number", "minimum": -100.0, "maximum": -10.0}},
}
for val, label in [(float("-inf"), "-Inf"), (float("inf"), "Inf"), (float("nan"), "NaN")]:
    try:
        validate_schema({"val": val}, neg_range_schema)
        record_result(f"4.6_{label}", f"Negative range schema rejects {label}", False, "Unexpectedly accepted")
    except ValidationError as exc:
        record_result(f"4.6_{label}", f"Negative range schema rejects {label}", "non-finite number" in str(exc), str(exc))



# ===========================================================================
# Section 5: Regression & Concurrency Hardening Sanity Check
# ===========================================================================

print("\n--- SECTION 5: Concurrency & State Machine Sanity ---")

# 5.1: State Machine Generation Atomicity on Rejections
spec = JobSpec(job_id="job_test", job_type="test", generation=1)
sm = JobStateMachine(spec)
sm.transition(JobStatus.QUEUED, generation=2)
sm.transition(JobStatus.RUNNING, generation=3)
# Attempt invalid transition from RUNNING to SUBMITTED with higher generation 5
try:
    sm.transition(JobStatus.SUBMITTED, generation=5)
    record_result("5.1", "State machine rejects invalid transition", False, "Transition unexpectedly allowed")
except InvalidStateTransitionError:
    record_result("5.1", "State machine rejects invalid transition", True)

# Check generation was NOT updated
record_result("5.2", "Generation remains atomic (3) on rejected transition", sm.generation == 3, f"Generation changed to {sm.generation}")

# 5.3: CancellationCoordinator Re-Entrancy
coord = CancellationCoordinator()
tok = coord.register_token("job_reentrant")

callback_invoked = False
callback_queries_succeeded = False

def reentrant_callback() -> None:
    global callback_invoked, callback_queries_succeeded
    callback_invoked = True
    # Query coordinator while callback is firing
    t = coord.get_token("job_reentrant")
    is_due = coord.is_preemption_due("job_reentrant")
    deadline = coord.get_preemption_deadline("job_reentrant")
    if t is tok and not is_due and deadline is not None:
        callback_queries_succeeded = True

tok.register_callback(reentrant_callback)

# Trigger cancellation
coord.request_cancellation("job_reentrant", "Adversarial test")
record_result("5.3", "CancellationCoordinator completes without re-entrancy deadlock", callback_invoked and callback_queries_succeeded)


# ===========================================================================
# Summary
# ===========================================================================

print("\n============================================================")
print(f"VERIFICATION SUITE SUMMARY: {passed_count} PASSED, {failed_count} FAILED")
print("============================================================")

if failed_count > 0:
    print("VERDICT: REQUEST_CHANGES (Hardening checks failed!)")
    sys.exit(1)
else:
    print("VERDICT: APPROVE (All hardening checks passed cleanly!)")
    sys.exit(0)
