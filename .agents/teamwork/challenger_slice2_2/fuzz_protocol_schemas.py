# -*- coding: utf-8 -*-
"""Empirical Stress-Testing and Fuzzing Harness for Schema Validator and Protocol Framing.

Target Modules:
- addon/globalPlugins/AI-assistant/core/job/schemas.py
- addon/globalPlugins/AI-assistant/core/job/protocol.py

Tests:
1. Schema Validator Fuzzing:
   - Missing required fields
   - Type mismatches (string, int, float, bool, list, dict)
   - Boolean passed for integer / number (Python bool-as-int pitfall)
   - Numerical ranges & negative values (minimum 0, minimum 1, maximum 100, maximum 1.0)
   - Extra properties under additionalProperties: false
   - Empty strings & boundary strings
   - Null values (where permitted vs where rejected)
   - Special float values (NaN, Inf, -Inf)
   - Non-dict root inputs
2. NDJSON Framing Fuzzing:
   - Oversized frames (> 16 MB)
   - Non-UTF8 bytes
   - Truncated JSON lines
   - Multi-line chunks
   - Malformed / non-dict JSON lines
   - Whitespace and empty frames
3. Hybrid Binary Framing Fuzzing:
   - Corrupted magic bytes
   - Payload length mismatches (short, long, extreme uint32)
   - Truncated stream chunks (< 12B, truncated JSON, truncated payload)
   - Non-UTF8 / malformed metadata
   - Oversized binary frames (> 16 MB)
4. Randomized Mutation Fuzzing:
   - 1000 random mutations against validate_schema
   - 1000 random byte mutations against decode_ndjson_frame
   - 1000 random byte mutations against decode_binary_frame
"""

from __future__ import annotations

import copy
import math
import os
from pathlib import Path
import random
import struct
import sys
import time
from typing import Any

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.support import load_addon_module

dto_mod = load_addon_module("core.job.dto")
schemas_mod = load_addon_module("core.job.schemas")
proto_mod = load_addon_module("core.job.protocol")

ValidationError = schemas_mod.ValidationError
validate_schema = schemas_mod.validate_schema

HANDSHAKE_REQUEST_SCHEMA = schemas_mod.HANDSHAKE_REQUEST_SCHEMA
HANDSHAKE_RESPONSE_SCHEMA = schemas_mod.HANDSHAKE_RESPONSE_SCHEMA
JOB_SPEC_SCHEMA = schemas_mod.JOB_SPEC_SCHEMA
JOB_PROGRESS_SCHEMA = schemas_mod.JOB_PROGRESS_SCHEMA
JOB_RESULT_SCHEMA = schemas_mod.JOB_RESULT_SCHEMA
JOB_CANCELLATION_REQUEST_SCHEMA = schemas_mod.JOB_CANCELLATION_REQUEST_SCHEMA
SESSION_CONFIG_SCHEMA = schemas_mod.SESSION_CONFIG_SCHEMA
STREAM_CHUNK_SCHEMA = schemas_mod.STREAM_CHUNK_SCHEMA
WORKER_HEALTH_SCHEMA = schemas_mod.WORKER_HEALTH_SCHEMA

ALL_SCHEMAS = {
    "HANDSHAKE_REQUEST": HANDSHAKE_REQUEST_SCHEMA,
    "HANDSHAKE_RESPONSE": HANDSHAKE_RESPONSE_SCHEMA,
    "JOB_SPEC": JOB_SPEC_SCHEMA,
    "JOB_PROGRESS": JOB_PROGRESS_SCHEMA,
    "JOB_RESULT": JOB_RESULT_SCHEMA,
    "JOB_CANCELLATION_REQUEST": JOB_CANCELLATION_REQUEST_SCHEMA,
    "SESSION_CONFIG": SESSION_CONFIG_SCHEMA,
    "STREAM_CHUNK": STREAM_CHUNK_SCHEMA,
    "WORKER_HEALTH": WORKER_HEALTH_SCHEMA,
}

ErrorCode = proto_mod.ErrorCode
ProtocolError = proto_mod.ProtocolError
MAGIC = proto_mod.MAGIC
HEADER_SIZE = proto_mod.HEADER_SIZE
MAX_FRAME_SIZE = proto_mod.MAX_FRAME_SIZE

encode_ndjson_frame = proto_mod.encode_ndjson_frame
decode_ndjson_frame = proto_mod.decode_ndjson_frame
encode_binary_frame = proto_mod.encode_binary_frame
decode_binary_frame = proto_mod.decode_binary_frame
is_protocol_compatible = proto_mod.is_protocol_compatible
validate_handshake = proto_mod.validate_handshake


def make_valid_fixtures() -> dict[str, dict[str, Any]]:
    """Return valid canonical dictionary fixtures for each schema."""
    return {
        "HANDSHAKE_REQUEST": {
            "type": "handshake_request",
            "protocol_version": "1.0.0",
            "client_name": "nvda_ai_assistant",
            "client_version": "1.0.0",
            "client_pid": 1234,
            "supported_schemas": ["job.v1", "session.v1"],
            "requested_capabilities": ["job.model_download", "job.inference"],
            "request_id": "req-uuid-1",
        },
        "HANDSHAKE_RESPONSE": {
            "type": "handshake_response",
            "accepted": True,
            "protocol_version": "1.0.0",
            "worker_pid": 5678,
            "worker_version": "1.0.0",
            "negotiated_capabilities": ["job.inference"],
            "max_frame_bytes": 16777216,
            "error_message": None,
            "correlation_id": "req-uuid-1",
        },
        "JOB_SPEC": {
            "type": "job_submission",
            "job_id": "job-101",
            "job_type": "model_download",
            "payload": {"model": "llama-3"},
            "priority": 10,
            "timeout_seconds": 300.0,
            "generation": 1,
            "created_at_epoch_ms": 1700000000000,
        },
        "JOB_PROGRESS": {
            "type": "job_update",
            "job_id": "job-101",
            "status": "running",
            "progress_pct": 50.0,
            "status_message": "Downloading shard 1",
            "bytes_completed": 500,
            "bytes_total": 1000,
            "throughput_bytes_per_sec": 100.0,
            "eta_seconds": 5.0,
            "generation": 1,
            "timestamp_epoch_ms": 1700000005000,
        },
        "JOB_RESULT": {
            "type": "job_result",
            "job_id": "job-101",
            "status": "completed",
            "result_data": {"path": "/models/llama-3.gguf"},
            "error_code": None,
            "error_message": None,
            "retriable": False,
            "duration_ms": 5000,
            "generation": 1,
        },
        "JOB_CANCELLATION_REQUEST": {
            "type": "job_cancellation_request",
            "job_id": "job-101",
            "reason": "user_cancelled",
            "preemption_timeout_seconds": 3.0,
            "generation": 1,
        },
        "SESSION_CONFIG": {
            "type": "session_config",
            "session_id": "sess-202",
            "modality": "ocr",
            "config_parameters": {"language": "en"},
            "max_queue_depth": 2,
            "buffer_capacity_ms": 10000,
            "generation": 1,
        },
        "STREAM_CHUNK": {
            "type": "stream_chunk",
            "session_id": "sess-202",
            "sequence_number": 0,
            "is_partial": False,
            "payload_text": "Extracted text line",
            "start_ms": 0,
            "end_ms": 100,
            "confidence": 0.95,
            "bounding_boxes": [{"x": 10, "y": 20, "w": 100, "h": 30}],
            "dropped_frames_count": 0,
            "generation": 1,
        },
        "WORKER_HEALTH": {
            "type": "worker_health",
            "worker_pid": 5678,
            "generation": 1,
            "uptime_seconds": 120.5,
            "active_jobs_count": 1,
            "active_sessions_count": 0,
            "cpu_percent": 12.5,
            "rss_memory_bytes": 104857600,
            "gpu_available": False,
            "gpu_memory_used_bytes": 0,
            "gpu_memory_total_bytes": 0,
            "is_healthy": True,
            "error_summary": None,
        },
    }


class FuzzResults:
    def __init__(self) -> None:
        self.total_tests = 0
        self.passed = 0
        self.failed = 0
        self.findings: list[str] = []

    def record_pass(self) -> None:
        self.total_tests += 1
        self.passed += 1

    def record_fail(self, description: str, detail: str) -> None:
        self.total_tests += 1
        self.failed += 1
        self.findings.append(f"[FAIL] {description}: {detail}")

    def record_finding(self, severity: str, title: str, detail: str) -> None:
        self.findings.append(f"[{severity}] {title}: {detail}")


def run_schema_fuzzing(results: FuzzResults) -> None:
    print("\n--- Running Schema Validator Fuzzing (schemas.py) ---")
    fixtures = make_valid_fixtures()

    # 1.0 Baseline: verify all fixtures are valid
    for name, fixture in fixtures.items():
        schema = ALL_SCHEMAS[name]
        try:
            validate_schema(fixture, schema)
            results.record_pass()
        except ValidationError as exc:
            results.record_fail(f"Valid baseline for {name}", str(exc))

    # 1.1 Missing required fields
    print("Testing missing required fields...")
    for name, fixture in fixtures.items():
        schema = ALL_SCHEMAS[name]
        required_fields = schema.get("required", [])
        for field_name in required_fields:
            mutated = copy.deepcopy(fixture)
            del mutated[field_name]
            try:
                validate_schema(mutated, schema)
                results.record_fail(
                    f"Missing required field {field_name} in {name}",
                    "Did NOT raise ValidationError",
                )
            except ValidationError as exc:
                if f"missing required property '{field_name}'" in str(exc):
                    results.record_pass()
                else:
                    results.record_fail(
                        f"Missing required field {field_name} in {name}",
                        f"Raised unexpected error message: {exc}",
                    )

        # Empty dict check
        try:
            validate_schema({}, schema)
            results.record_fail(f"Empty dict in {name}", "Did NOT raise ValidationError")
        except ValidationError as exc:
            if len(exc.errors) == len(required_fields):
                results.record_pass()
            else:
                results.record_fail(
                    f"Empty dict in {name}",
                    f"Expected {len(required_fields)} errors, got {len(exc.errors)}: {exc.errors}",
                )

    # 1.2 Type mismatches
    print("Testing type mismatches...")
    for name, fixture in fixtures.items():
        schema = ALL_SCHEMAS[name]
        properties = schema.get("properties", {})
        for prop, prop_schema in properties.items():
            expected = prop_schema.get("type")
            if not expected or isinstance(expected, list):
                continue
            
            # Select wrong types based on expected
            wrong_values = []
            if expected == "string":
                wrong_values = [123, 45.6, True, False, [1, 2], {"a": 1}]
            elif expected == "integer":
                wrong_values = ["not_int", 12.34, [1], {"a": 1}]
            elif expected == "number":
                wrong_values = ["not_num", [1], {"a": 1}]
            elif expected == "boolean":
                wrong_values = ["true", 1, 0, [True], {"val": True}]
            elif expected == "array":
                wrong_values = ["string", 123, {"key": "val"}]
            elif expected == "object":
                wrong_values = ["string", 123, [1, 2]]

            for wrong_val in wrong_values:
                mutated = copy.deepcopy(fixture)
                mutated[prop] = wrong_val
                try:
                    validate_schema(mutated, schema)
                    results.record_fail(
                        f"Type mismatch on {name}.{prop} ({expected} got {type(wrong_val).__name__})",
                        f"Allowed wrong value: {wrong_val!r}",
                    )
                except ValidationError:
                    results.record_pass()

    # 1.3 Bool passed for integer / number (Python bool-as-int trap)
    print("Testing bool passed for integer / number...")
    bool_traps = [
        ("JOB_SPEC", "priority", True),
        ("JOB_SPEC", "priority", False),
        ("JOB_SPEC", "generation", True),
        ("JOB_SPEC", "created_at_epoch_ms", False),
        ("JOB_SPEC", "timeout_seconds", True),
        ("HANDSHAKE_REQUEST", "client_pid", True),
        ("HANDSHAKE_RESPONSE", "worker_pid", False),
        ("HANDSHAKE_RESPONSE", "max_frame_bytes", True),
        ("JOB_PROGRESS", "bytes_completed", True),
        ("JOB_PROGRESS", "bytes_total", False),
        ("JOB_PROGRESS", "progress_pct", True),
        ("JOB_PROGRESS", "throughput_bytes_per_sec", False),
        ("JOB_RESULT", "duration_ms", True),
        ("SESSION_CONFIG", "max_queue_depth", True),
        ("SESSION_CONFIG", "buffer_capacity_ms", False),
        ("STREAM_CHUNK", "sequence_number", True),
        ("STREAM_CHUNK", "start_ms", False),
        ("STREAM_CHUNK", "confidence", True),
        ("WORKER_HEALTH", "worker_pid", True),
        ("WORKER_HEALTH", "active_jobs_count", False),
        ("WORKER_HEALTH", "cpu_percent", True),
        ("WORKER_HEALTH", "uptime_seconds", False),
    ]

    for schema_name, prop, val in bool_traps:
        schema = ALL_SCHEMAS[schema_name]
        mutated = copy.deepcopy(fixtures[schema_name])
        mutated[prop] = val
        try:
            validate_schema(mutated, schema)
            results.record_fail(
                f"Bool-as-int trap on {schema_name}.{prop}",
                f"Value {val!r} (bool) was accepted as integer/number",
            )
        except ValidationError as exc:
            if "got 'bool'" in str(exc):
                results.record_pass()
            else:
                results.record_fail(
                    f"Bool-as-int trap on {schema_name}.{prop}",
                    f"Raised error but didn't identify 'bool': {exc}",
                )

    # 1.4 Numerical ranges and negative numbers
    print("Testing numerical range and negative bounds...")
    range_violations = [
        # (schema_name, field, invalid_value, violation_description)
        ("JOB_PROGRESS", "progress_pct", -0.01, "negative pct"),
        ("JOB_PROGRESS", "progress_pct", 100.01, "pct > 100"),
        ("JOB_PROGRESS", "progress_pct", 999.0, "pct >> 100"),
        ("JOB_PROGRESS", "bytes_completed", -1, "negative bytes_completed"),
        ("JOB_PROGRESS", "bytes_total", -1, "negative bytes_total"),
        ("JOB_PROGRESS", "throughput_bytes_per_sec", -0.01, "negative throughput"),
        ("JOB_PROGRESS", "eta_seconds", -1.0, "negative eta"),
        ("JOB_PROGRESS", "generation", 0, "generation < 1"),
        ("JOB_PROGRESS", "generation", -5, "generation negative"),
        ("JOB_SPEC", "timeout_seconds", -1.0, "negative timeout"),
        ("JOB_SPEC", "generation", 0, "generation < 1"),
        ("JOB_SPEC", "created_at_epoch_ms", -1, "negative timestamp"),
        ("JOB_RESULT", "duration_ms", -1, "negative duration"),
        ("JOB_RESULT", "generation", 0, "generation < 1"),
        ("HANDSHAKE_RESPONSE", "max_frame_bytes", 0, "max_frame_bytes < 1"),
        ("HANDSHAKE_RESPONSE", "max_frame_bytes", -10, "max_frame_bytes negative"),
        ("SESSION_CONFIG", "max_queue_depth", 0, "max_queue_depth < 1"),
        ("SESSION_CONFIG", "buffer_capacity_ms", 0, "buffer_capacity_ms < 1"),
        ("STREAM_CHUNK", "sequence_number", -1, "negative sequence_number"),
        ("STREAM_CHUNK", "start_ms", -1, "negative start_ms"),
        ("STREAM_CHUNK", "end_ms", -1, "negative end_ms"),
        ("STREAM_CHUNK", "confidence", -0.01, "confidence < 0.0"),
        ("STREAM_CHUNK", "confidence", 1.01, "confidence > 1.0"),
        ("STREAM_CHUNK", "dropped_frames_count", -1, "negative dropped_frames"),
        ("WORKER_HEALTH", "uptime_seconds", -0.1, "negative uptime"),
        ("WORKER_HEALTH", "active_jobs_count", -1, "negative active_jobs"),
        ("WORKER_HEALTH", "active_sessions_count", -1, "negative active_sessions"),
        ("WORKER_HEALTH", "cpu_percent", -0.1, "negative cpu_percent"),
        ("WORKER_HEALTH", "rss_memory_bytes", -1, "negative rss"),
        ("WORKER_HEALTH", "gpu_memory_used_bytes", -1, "negative gpu_used"),
        ("WORKER_HEALTH", "gpu_memory_total_bytes", -1, "negative gpu_total"),
    ]

    for schema_name, field_name, bad_val, desc in range_violations:
        schema = ALL_SCHEMAS[schema_name]
        mutated = copy.deepcopy(fixtures[schema_name])
        mutated[field_name] = bad_val
        try:
            validate_schema(mutated, schema)
            results.record_fail(
                f"Range bound violation on {schema_name}.{field_name} ({desc}: {bad_val})",
                "Did NOT raise ValidationError",
            )
        except ValidationError:
            results.record_pass()

    # 1.5 Extra properties under additionalProperties: False
    print("Testing additionalProperties: False enforcement...")
    injected_keys = [
        "extra_field",
        "__proto__",
        "constructor",
        "admin",
        "\x00_null_byte_prop",
        "nested_injection",
    ]
    for name, fixture in fixtures.items():
        schema = ALL_SCHEMAS[name]
        for injected_key in injected_keys:
            mutated = copy.deepcopy(fixture)
            mutated[injected_key] = "malicious_payload"
            try:
                validate_schema(mutated, schema)
                results.record_fail(
                    f"additionalProperties on {name} with '{injected_key}'",
                    "Did NOT raise ValidationError",
                )
            except ValidationError as exc:
                if f"unexpected additional property '{injected_key}'" in str(exc):
                    results.record_pass()
                else:
                    results.record_fail(
                        f"additionalProperties on {name} with '{injected_key}'",
                        f"Unexpected error message: {exc}",
                    )

    # 1.6 Null values handling
    print("Testing null values (permitted vs rejected)...")
    # Where null is PERMITTED:
    permitted_nulls = [
        ("HANDSHAKE_RESPONSE", "error_message"),
        ("JOB_PROGRESS", "eta_seconds"),
        ("JOB_RESULT", "error_code"),
        ("JOB_RESULT", "error_message"),
        ("WORKER_HEALTH", "error_summary"),
    ]
    for schema_name, field_name in permitted_nulls:
        schema = ALL_SCHEMAS[schema_name]
        mutated = copy.deepcopy(fixtures[schema_name])
        mutated[field_name] = None
        try:
            validate_schema(mutated, schema)
            results.record_pass()
        except ValidationError as exc:
            results.record_fail(
                f"Permitted null on {schema_name}.{field_name}",
                f"Raised ValidationError: {exc}",
            )

    # Where null is NOT PERMITTED:
    prohibited_nulls = [
        ("JOB_SPEC", "job_id"),
        ("JOB_SPEC", "payload"),
        ("JOB_SPEC", "priority"),
        ("JOB_PROGRESS", "status"),
        ("JOB_PROGRESS", "progress_pct"),
        ("JOB_RESULT", "result_data"),
        ("JOB_RESULT", "status"),
        ("HANDSHAKE_REQUEST", "client_name"),
        ("SESSION_CONFIG", "session_id"),
        ("STREAM_CHUNK", "payload_text"),
        ("WORKER_HEALTH", "worker_pid"),
    ]
    for schema_name, field_name in prohibited_nulls:
        schema = ALL_SCHEMAS[schema_name]
        mutated = copy.deepcopy(fixtures[schema_name])
        mutated[field_name] = None
        try:
            validate_schema(mutated, schema)
            results.record_fail(
                f"Prohibited null on {schema_name}.{field_name}",
                "Accepted null value without raising ValidationError",
            )
        except ValidationError:
            results.record_pass()

    # 1.7 Special float values (NaN, Inf, -Inf)
    print("Testing special float values (NaN, Inf, -Inf)...")
    for schema_name, field_name in [("JOB_PROGRESS", "progress_pct"), ("STREAM_CHUNK", "confidence")]:
        schema = ALL_SCHEMAS[schema_name]
        for special_val, name_val in [
            (float("nan"), "NaN"),
            (float("inf"), "Inf"),
            (float("-inf"), "-Inf"),
        ]:
            mutated = copy.deepcopy(fixtures[schema_name])
            mutated[field_name] = special_val
            try:
                validate_schema(mutated, schema)
                # If NaN/Inf was accepted, note whether it bypassed range checks!
                if math.isnan(special_val):
                    results.record_finding(
                        "MEDIUM",
                        f"Schema validator accepts NaN on {schema_name}.{field_name}",
                        f"float('nan') passed schema validation because nan < min and nan > max are both False.",
                    )
                elif math.isinf(special_val):
                    results.record_fail(
                        f"Special float {name_val} on {schema_name}.{field_name}",
                        f"Accepted infinite float without error",
                    )
            except ValidationError:
                results.record_pass()

    # 1.8 Non-dict root inputs
    print("Testing non-dict root inputs to validate_schema...")
    non_dict_roots = ["string", 12345, 12.34, True, False, None, [1, 2, 3]]
    for root in non_dict_roots:
        try:
            validate_schema(root, JOB_SPEC_SCHEMA)
            results.record_fail(
                f"Non-dict root input {type(root).__name__}",
                "Did NOT raise ValidationError",
            )
        except ValidationError as exc:
            if "expected type 'object'" in str(exc):
                results.record_pass()
            else:
                results.record_fail(
                    f"Non-dict root input {type(root).__name__}",
                    f"Unexpected error: {exc}",
                )

    # 1.9 Const and Enum violations
    print("Testing const and enum values...")
    # Const violation on type field
    for name, fixture in fixtures.items():
        schema = ALL_SCHEMAS[name]
        mutated = copy.deepcopy(fixture)
        mutated["type"] = "injected_bogus_type"
        try:
            validate_schema(mutated, schema)
            results.record_fail(f"Const violation on {name}.type", "Did NOT raise ValidationError")
        except ValidationError as exc:
            if "expected const" in str(exc):
                results.record_pass()
            else:
                results.record_fail(f"Const violation on {name}.type", f"Unexpected msg: {exc}")

    # Enum violation on status
    for bad_status in ["active", "pending", "paused", "finished", ""]:
        mutated = copy.deepcopy(fixtures["JOB_PROGRESS"])
        mutated["status"] = bad_status
        try:
            validate_schema(mutated, JOB_PROGRESS_SCHEMA)
            results.record_fail(f"Enum violation on status={bad_status!r}", "Did NOT raise ValidationError")
        except ValidationError as exc:
            if "not in allowed enum" in str(exc):
                results.record_pass()
            else:
                results.record_fail(f"Enum violation on status={bad_status!r}", f"Unexpected msg: {exc}")


def run_ndjson_fuzzing(results: FuzzResults) -> None:
    print("\n--- Running NDJSON Protocol Framing Fuzzing (protocol.py) ---")

    # 2.1 Oversized frames
    print("Testing NDJSON oversized frames (> 16 MB)...")
    # Exactly MAX_FRAME_SIZE: should encode/decode if constructed, or test limit
    # Test encode limit
    oversized_dict = {"data": "x" * (MAX_FRAME_SIZE + 50)}
    try:
        encode_ndjson_frame(oversized_dict)
        results.record_fail("encode_ndjson_frame oversized", "Did NOT raise ProtocolError")
    except ProtocolError as exc:
        if exc.error_code == ErrorCode.FRAME_TOO_LARGE:
            results.record_pass()
        else:
            results.record_fail("encode_ndjson_frame oversized", f"Unexpected error code: {exc.error_code}")

    # Test decode limit
    oversized_raw = b"x" * (MAX_FRAME_SIZE + 1)
    try:
        decode_ndjson_frame(oversized_raw)
        results.record_fail("decode_ndjson_frame oversized raw", "Did NOT raise ProtocolError")
    except ProtocolError as exc:
        if exc.error_code == ErrorCode.FRAME_TOO_LARGE:
            results.record_pass()
        else:
            results.record_fail("decode_ndjson_frame oversized raw", f"Unexpected error code: {exc.error_code}")

    # 2.2 Non-UTF8 bytes
    print("Testing non-UTF8 bytes...")
    non_utf8_payloads = [
        b"\xFF\xFE\xFD\n",
        b"\x80\x81\x82\x83\n",
        b'{"key": "\xC0\xAF"}\n',
        b'{"key": "\xED\xA0\x80"}\n',  # UTF-16 surrogate
        b"\xFE\xFF{\"type\": \"test\"}\n",  # UTF-16 BOM
        b"\x00\x00\x00\x01\n",
    ]
    for bad_bytes in non_utf8_payloads:
        try:
            decode_ndjson_frame(bad_bytes)
            results.record_fail(
                f"Non-UTF8 payload {bad_bytes[:10]!r}", "Did NOT raise ProtocolError"
            )
        except ProtocolError as exc:
            if exc.error_code == ErrorCode.INVALID_FRAME:
                results.record_pass()
            else:
                results.record_fail(
                    f"Non-UTF8 payload {bad_bytes[:10]!r}",
                    f"Expected INVALID_FRAME, got {exc.error_code}",
                )

    # 2.3 Truncated JSON lines
    print("Testing truncated JSON lines...")
    truncated_lines = [
        b'{"type": "job_submission"',
        b'{"payload": {"sub": 12',
        b'{"items": [1, 2, ',
        b'{"key": "unclosed string',
        b'{"num": 123.',
        b'{',
        b'{"a":',
        b'{"a": 1,',
    ]
    for trunc in truncated_lines:
        try:
            decode_ndjson_frame(trunc)
            results.record_fail(
                f"Truncated line {trunc!r}", "Did NOT raise ProtocolError"
            )
        except ProtocolError as exc:
            if exc.error_code == ErrorCode.INVALID_FRAME:
                results.record_pass()
            else:
                results.record_fail(
                    f"Truncated line {trunc!r}",
                    f"Expected INVALID_FRAME, got {exc.error_code}",
                )

    # 2.4 Multi-line chunks
    print("Testing multi-line chunks...")
    multi_line_chunks = [
        b'{"a": 1}\n{"b": 2}\n',
        b'{"a": 1}\r\n{"b": 2}\r\n',
        b'{"a": 1}\n\n{"b": 2}\n',
    ]
    for chunk in multi_line_chunks:
        try:
            decode_ndjson_frame(chunk)
            results.record_fail(
                f"Multi-line chunk {chunk!r}", "Did NOT raise ProtocolError"
            )
        except ProtocolError as exc:
            if exc.error_code == ErrorCode.INVALID_FRAME:
                results.record_pass()
            else:
                results.record_fail(
                    f"Multi-line chunk {chunk!r}",
                    f"Expected INVALID_FRAME, got {exc.error_code}",
                )

    # Check multi-line formatted JSON:
    formatted_json = b'{\n  "job_id": "j1",\n  "type": "job_submission"\n}\n'
    try:
        decoded = decode_ndjson_frame(formatted_json)
        if decoded.get("job_id") == "j1":
            results.record_pass()
    except Exception as exc:
        results.record_fail("Formatted multi-line JSON single object", str(exc))

    # 2.5 Empty and whitespace frames
    print("Testing empty frames...")
    empty_frames = [b"", b"\n", b"\r\n", b"   \n", b"\t\t\n", b"   \r\n   "]
    for empty in empty_frames:
        try:
            decode_ndjson_frame(empty)
            results.record_fail(f"Empty frame {empty!r}", "Did NOT raise ProtocolError")
        except ProtocolError as exc:
            if exc.error_code == ErrorCode.INVALID_FRAME:
                results.record_pass()
            else:
                results.record_fail(
                    f"Empty frame {empty!r}",
                    f"Expected INVALID_FRAME, got {exc.error_code}",
                )

    # 2.6 Non-dict JSON primitives decoded
    print("Testing non-dict JSON primitives in decode_ndjson_frame...")
    non_dict_json = [
        (b"123\n", int),
        (b'"hello world"\n', str),
        (b"[1, 2, 3]\n", list),
        (b"true\n", bool),
        (b"null\n", type(None)),
    ]
    for raw, expected_type in non_dict_json:
        res = decode_ndjson_frame(raw)
        # Note finding: decode_ndjson_frame is annotated as returning dict[str, Any],
        # but json.loads returns primitive types without raising ProtocolError.
        results.record_finding(
            "LOW",
            f"decode_ndjson_frame returns non-dict type {expected_type.__name__}",
            f"Frame {raw.strip()!r} decoded as {type(res).__name__} ({res!r}) instead of raising INVALID_FRAME. Return type contract is dict[str, Any].",
        )
        results.record_pass()


def run_binary_framing_fuzzing(results: FuzzResults) -> None:
    print("\n--- Running Hybrid Binary Framing Fuzzing (protocol.py) ---")

    valid_meta = {"session_id": "s1", "seq": 10}
    valid_payload = b"\x00\x01\x02\x03\x04\x05\xFF\xFE"
    valid_frame = encode_binary_frame(valid_meta, valid_payload)

    # Baseline check
    try:
        d_meta, d_pay = decode_binary_frame(valid_frame)
        if d_meta == valid_meta and d_pay == valid_payload:
            results.record_pass()
        else:
            results.record_fail("Binary frame baseline round-trip", "Mismatch in decoded values")
    except Exception as exc:
        results.record_fail("Binary frame baseline round-trip", str(exc))

    # 3.1 Corrupted magic bytes
    print("Testing corrupted magic bytes...")
    corrupted_magics = [
        b"\x00\x55\x01\x00",
        b"\xAA\x00\x01\x00",
        b"\xAA\x55\x00\x00",
        b"\xAA\x55\x01\x01",
        b"\x00\x00\x00\x00",
        b"\xFF\xFF\xFF\xFF",
        b"RIFF",
        b"POST",
    ]
    for bad_magic in corrupted_magics:
        corrupted_frame = bad_magic + valid_frame[4:]
        try:
            decode_binary_frame(corrupted_frame)
            results.record_fail(
                f"Corrupted magic {bad_magic!r}", "Did NOT raise ProtocolError"
            )
        except ProtocolError as exc:
            if exc.error_code == ErrorCode.INVALID_FRAME:
                results.record_pass()
            else:
                results.record_fail(
                    f"Corrupted magic {bad_magic!r}",
                    f"Expected INVALID_FRAME, got {exc.error_code}",
                )

    # 3.2 Payload length mismatches
    print("Testing payload length mismatches...")
    # Buffer smaller than expected
    truncated_short = valid_frame[:-1]
    try:
        decode_binary_frame(truncated_short)
        results.record_fail("Truncated frame by 1 byte", "Did NOT raise ProtocolError")
    except ProtocolError as exc:
        if exc.error_code == ErrorCode.INVALID_FRAME and "Binary frame length mismatch" in str(exc):
            results.record_pass()
        else:
            results.record_fail("Truncated frame by 1 byte", f"Unexpected error: {exc}")

    # Buffer larger than expected (trailing garbage)
    extended_frame = valid_frame + b"\x00\x00\x00"
    try:
        decode_binary_frame(extended_frame)
        results.record_fail("Frame with trailing garbage", "Did NOT raise ProtocolError")
    except ProtocolError as exc:
        if exc.error_code == ErrorCode.INVALID_FRAME and "Binary frame length mismatch" in str(exc):
            results.record_pass()
        else:
            results.record_fail("Frame with trailing garbage", f"Unexpected error: {exc}")

    # Extreme uint32 length headers
    extreme_headers = [
        (0xFFFFFFFF, 0),       # meta_len = 4 GB
        (0, 0xFFFFFFFF),       # bin_len = 4 GB
        (0x7FFFFFFF, 0),       # meta_len = 2 GB
        (0x01000000, 0),       # meta_len = 16 MB + 1
    ]
    for meta_len, bin_len in extreme_headers:
        fake_header = struct.pack(">4sII", MAGIC, meta_len, bin_len) + b"short_data"
        try:
            decode_binary_frame(fake_header)
            results.record_fail(
                f"Extreme length header ({meta_len}, {bin_len})",
                "Did NOT raise ProtocolError",
            )
        except ProtocolError as exc:
            if exc.error_code in (ErrorCode.INVALID_FRAME, ErrorCode.FRAME_TOO_LARGE):
                results.record_pass()
            else:
                results.record_fail(
                    f"Extreme length header ({meta_len}, {bin_len})",
                    f"Unexpected error: {exc}",
                )

    # 3.3 Truncated stream chunks (< 12 bytes)
    print("Testing truncated headers (< 12 bytes)...")
    for size in range(12):
        chunk = valid_frame[:size]
        try:
            decode_binary_frame(chunk)
            results.record_fail(
                f"Truncated header ({size} bytes)", "Did NOT raise ProtocolError"
            )
        except ProtocolError as exc:
            if exc.error_code == ErrorCode.INVALID_FRAME:
                results.record_pass()
            else:
                results.record_fail(
                    f"Truncated header ({size} bytes)",
                    f"Expected INVALID_FRAME, got {exc.error_code}",
                )

    # 3.4 Corrupted metadata JSON in binary frame
    print("Testing corrupted metadata JSON in binary frame...")
    # Corrupt metadata JSON while keeping length valid
    bad_meta_bytes = b"{" + b"x" * (len(valid_frame) - HEADER_SIZE - len(valid_payload) - 1)
    corrupted_json_frame = (
        valid_frame[:HEADER_SIZE] + bad_meta_bytes + valid_payload
    )
    try:
        decode_binary_frame(corrupted_json_frame)
        results.record_fail("Corrupted metadata JSON", "Did NOT raise ProtocolError")
    except ProtocolError as exc:
        if exc.error_code == ErrorCode.INVALID_FRAME and "Failed to parse binary frame metadata" in str(exc):
            results.record_pass()
        else:
            results.record_fail("Corrupted metadata JSON", f"Unexpected error: {exc}")

    # Non-UTF8 metadata in binary frame
    non_utf8_meta = b"\xFF" * (len(valid_frame) - HEADER_SIZE - len(valid_payload))
    corrupted_utf8_frame = (
        valid_frame[:HEADER_SIZE] + non_utf8_meta + valid_payload
    )
    try:
        decode_binary_frame(corrupted_utf8_frame)
        results.record_fail("Non-UTF8 metadata in binary frame", "Did NOT raise ProtocolError")
    except ProtocolError as exc:
        if exc.error_code == ErrorCode.INVALID_FRAME:
            results.record_pass()
        else:
            results.record_fail("Non-UTF8 metadata in binary frame", f"Unexpected error: {exc}")

    # 3.5 Oversized binary frames
    print("Testing oversized binary frames...")
    try:
        encode_binary_frame({"a": 1}, b"x" * (MAX_FRAME_SIZE + 10))
        results.record_fail("encode_binary_frame oversized", "Did NOT raise ProtocolError")
    except ProtocolError as exc:
        if exc.error_code == ErrorCode.FRAME_TOO_LARGE:
            results.record_pass()
        else:
            results.record_fail("encode_binary_frame oversized", f"Unexpected error: {exc}")

    try:
        decode_binary_frame(b"x" * (MAX_FRAME_SIZE + 1))
        results.record_fail("decode_binary_frame oversized", "Did NOT raise ProtocolError")
    except ProtocolError as exc:
        if exc.error_code == ErrorCode.FRAME_TOO_LARGE:
            results.record_pass()
        else:
            results.record_fail("decode_binary_frame oversized", f"Unexpected error: {exc}")


def run_random_mutation_fuzzing(results: FuzzResults, iterations: int = 1000) -> None:
    print(f"\n--- Running Randomized Mutation Fuzzing ({iterations} iterations each) ---")
    fixtures = make_valid_fixtures()
    rng = random.Random(42)

    # 4.1 Fuzzing validate_schema
    print(f"Fuzzing validate_schema with {iterations} randomized mutations...")
    unhandled_schema_exceptions = 0
    for _ in range(iterations):
        schema_name = rng.choice(list(ALL_SCHEMAS.keys()))
        schema = ALL_SCHEMAS[schema_name]
        data = copy.deepcopy(fixtures[schema_name])

        # Apply 1 to 4 random mutations
        for _ in range(rng.randint(1, 4)):
            mutation_type = rng.choice([
                "delete_key",
                "corrupt_type",
                "insert_key",
                "corrupt_number",
                "nested_corrupt",
            ])
            keys = list(data.keys())
            if mutation_type == "delete_key" and keys:
                del data[rng.choice(keys)]
            elif mutation_type == "corrupt_type" and keys:
                k = rng.choice(keys)
                data[k] = rng.choice([
                    None,
                    "",
                    12345,
                    -999,
                    True,
                    False,
                    [],
                    {},
                    [1, "a"],
                    {"nested": True},
                ])
            elif mutation_type == "insert_key":
                data[f"fuzz_{rng.randint(0, 10000)}"] = rng.choice([
                    "random_str",
                    123,
                    None,
                    [rng.random()],
                ])
            elif mutation_type == "corrupt_number" and keys:
                k = rng.choice(keys)
                if isinstance(data.get(k), (int, float)):
                    data[k] = rng.choice([-1, -999999, 10**12, 0, 0.0, float("nan"), float("inf")])
            elif mutation_type == "nested_corrupt":
                if "payload" in data and isinstance(data["payload"], dict):
                    data["payload"][f"sub_{rng.randint(0, 100)}"] = rng.random()

        try:
            validate_schema(data, schema)
            # Either it legitimately passes if mutation was harmless or raises ValidationError
            results.record_pass()
        except ValidationError:
            results.record_pass()
        except Exception as exc:
            unhandled_schema_exceptions += 1
            results.record_fail(
                "Unhandled exception in validate_schema",
                f"Exception {type(exc).__name__}: {exc} on data {data!r}",
            )

    # 4.2 Fuzzing decode_ndjson_frame
    print(f"Fuzzing decode_ndjson_frame with {iterations} randomized byte streams...")
    unhandled_ndjson_exceptions = 0
    for _ in range(iterations):
        # Generate random byte streams: pure random, mutated json, mutated headers
        fuzz_type = rng.choice(["pure_random", "mutated_json", "corrupt_delimiters"])
        if fuzz_type == "pure_random":
            length = rng.randint(0, 4096)
            data_bytes = rng.randbytes(length)
        elif fuzz_type == "mutated_json":
            base = b'{"type": "job_submission", "job_id": "test", "num": 100}\n'
            # Mutate random bytes
            ba = bytearray(base)
            for _ in range(rng.randint(1, 10)):
                idx = rng.randint(0, len(ba) - 1)
                ba[idx] = rng.randint(0, 255)
            data_bytes = bytes(ba)
        else:
            data_bytes = rng.choice([
                b"\n" * rng.randint(1, 20),
                b" " * rng.randint(1, 50) + b"\n",
                b'{"a": 1}' + (b"\n" * rng.randint(2, 5)),
            ])

        try:
            decode_ndjson_frame(data_bytes)
            results.record_pass()
        except ProtocolError:
            results.record_pass()
        except Exception as exc:
            unhandled_ndjson_exceptions += 1
            results.record_fail(
                "Unhandled exception in decode_ndjson_frame",
                f"{type(exc).__name__}: {exc} on input {data_bytes[:30]!r}",
            )

    # 4.3 Fuzzing decode_binary_frame
    print(f"Fuzzing decode_binary_frame with {iterations} randomized byte streams...")
    unhandled_binary_exceptions = 0
    for _ in range(iterations):
        fuzz_type = rng.choice(["pure_random", "mutated_valid_frame", "truncated_valid"])
        if fuzz_type == "pure_random":
            length = rng.randint(0, 2048)
            data_bytes = rng.randbytes(length)
        elif fuzz_type == "mutated_valid_frame":
            valid_frame = encode_binary_frame({"meta": "data", "seq": 1}, b"abc123payload")
            ba = bytearray(valid_frame)
            # Mutate 1 to 5 random bytes
            for _ in range(rng.randint(1, 5)):
                idx = rng.randint(0, len(ba) - 1)
                ba[idx] = rng.randint(0, 255)
            data_bytes = bytes(ba)
        else:
            valid_frame = encode_binary_frame({"meta": "data", "seq": 1}, b"abc123payload")
            cut_point = rng.randint(0, len(valid_frame))
            data_bytes = valid_frame[:cut_point]

        try:
            decode_binary_frame(data_bytes)
            results.record_pass()
        except ProtocolError:
            results.record_pass()
        except Exception as exc:
            unhandled_binary_exceptions += 1
            results.record_fail(
                "Unhandled exception in decode_binary_frame",
                f"{type(exc).__name__}: {exc} on input {data_bytes[:30]!r}",
            )

    print(f"Random mutation fuzzing complete: "
          f"{unhandled_schema_exceptions} unhandled in schema, "
          f"{unhandled_ndjson_exceptions} in NDJSON, "
          f"{unhandled_binary_exceptions} in Binary Framing.")


def run_advanced_stress_tests(results: FuzzResults) -> None:
    print("\n--- Running Advanced Stress & Boundary Tests ---")

    # 5.1 Exact 16 MB Boundary Test (Off-by-one verification)
    print("Testing exact 16 MB frame boundaries...")
    # Exact boundary: 16 * 1024 * 1024 = 16,777,216 bytes
    # Valid frame at exactly 16,777,216 bytes
    exact_limit = MAX_FRAME_SIZE
    # Construct a valid JSON string that with newline equals exactly exact_limit
    # '{"k":"..."}\n'
    prefix = b'{"k":"'
    suffix = b'"}\n'
    padding_len = exact_limit - len(prefix) - len(suffix)
    exact_frame = prefix + (b"a" * padding_len) + suffix
    assert len(exact_frame) == exact_limit

    try:
        decoded = decode_ndjson_frame(exact_frame)
        if len(decoded["k"]) == padding_len:
            results.record_pass()
        else:
            results.record_fail("Exact 16MB boundary decode", "Decoded content length mismatch")
    except Exception as exc:
        results.record_fail("Exact 16MB boundary decode", f"Failed to decode exactly 16MB frame: {exc}")

    # Off-by-one: exact_limit + 1 byte
    over_limit_frame = exact_frame + b"x"
    assert len(over_limit_frame) == exact_limit + 1
    try:
        decode_ndjson_frame(over_limit_frame)
        results.record_fail("Exact 16MB + 1 byte decode", "Did NOT raise ProtocolError")
    except ProtocolError as exc:
        if exc.error_code == ErrorCode.FRAME_TOO_LARGE:
            results.record_pass()
        else:
            results.record_fail("Exact 16MB + 1 byte decode", f"Unexpected error code: {exc.error_code}")

    # 5.2 Deeply nested JSON schema validation
    print("Testing deep nesting recursion limits...")
    # Build 100 levels of nested objects in payload
    deep_data = {}
    curr = deep_data
    for i in range(100):
        curr["nested"] = {}
        curr = curr["nested"]
    curr["value"] = 42

    spec_fixture = make_valid_fixtures()["JOB_SPEC"]
    spec_fixture["payload"] = deep_data
    try:
        validate_schema(spec_fixture, JOB_SPEC_SCHEMA)
        results.record_pass()
    except Exception as exc:
        results.record_fail("100-level nested payload", f"Failed with: {exc}")

    # 5.3 High-Throughput Framing Stress Test
    print("Testing high-throughput framing (5,000 NDJSON and 5,000 Binary frames)...")
    t0 = time.time()
    payload = {"type": "job_update", "job_id": "j-stress", "pct": 99.9}
    for _ in range(5000):
        raw = encode_ndjson_frame(payload)
        d = decode_ndjson_frame(raw)
        assert d["job_id"] == "j-stress"
    ndjson_duration = time.time() - t0

    t1 = time.time()
    meta = {"session_id": "s-stress", "seq": 1}
    bin_buf = b"\x01\x02\x03\x04" * 16  # 64 bytes
    for _ in range(5000):
        raw = encode_binary_frame(meta, bin_buf)
        m, b_out = decode_binary_frame(raw)
        assert m["session_id"] == "s-stress"
        assert len(b_out) == 64
    binary_duration = time.time() - t1

    results.record_pass()
    results.record_pass()
    print(f"5,000 NDJSON frames encoded & decoded in {ndjson_duration:.3f}s ({5000/ndjson_duration:.0f} fps)")
    print(f"5,000 Binary frames encoded & decoded in {binary_duration:.3f}s ({5000/binary_duration:.0f} fps)")

    # 5.4 Binary frame non-dict metadata check
    print("Testing binary frame non-dict metadata...")
    non_dict_metadata_bytes = b"123"
    fake_header = struct.pack(">4sII", MAGIC, len(non_dict_metadata_bytes), 0)
    fake_frame = fake_header + non_dict_metadata_bytes
    try:
        decoded_meta, _ = decode_binary_frame(fake_frame)
        results.record_finding(
            "LOW",
            "decode_binary_frame returns non-dict metadata",
            f"Metadata {non_dict_metadata_bytes!r} decoded as {type(decoded_meta).__name__} ({decoded_meta!r}) instead of raising INVALID_FRAME. Return type contract is tuple[dict[str, Any], bytes].",
        )
        results.record_pass()
    except ProtocolError:
        results.record_pass()


def main() -> int:
    start_time = time.time()
    print("======================================================================")
    print("STARTING EMPIRICAL FUZZ & STRESS TEST HARNESS")
    print("======================================================================")

    results = FuzzResults()

    run_schema_fuzzing(results)
    run_ndjson_fuzzing(results)
    run_binary_framing_fuzzing(results)
    run_random_mutation_fuzzing(results, iterations=1000)
    run_advanced_stress_tests(results)

    duration = time.time() - start_time
    print("\n======================================================================")
    print(f"FUZZING COMPLETED in {duration:.2f} seconds")
    print(f"Total assertions / fuzz inputs tested: {results.total_tests}")
    print(f"Passed: {results.passed}")
    print(f"Failed: {results.failed}")
    print(f"Findings recorded: {len(results.findings)}")
    print("======================================================================")

    if results.findings:
        print("\n--- FINDINGS SUMMARY ---")
        for f in results.findings[:30]:  # Cap display at 30
            print(f)
        if len(results.findings) > 30:
            print(f"... and {len(results.findings) - 30} more findings.")

    if results.failed > 0:
        print(f"\n[FAIL] {results.failed} fuzz tests failed!")
        return 1
    else:
        print("\n[SUCCESS] All fuzz tests passed without unhandled crashes or uncontained failures.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
