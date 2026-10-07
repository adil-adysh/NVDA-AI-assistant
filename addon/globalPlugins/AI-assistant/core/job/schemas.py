# -*- coding: utf-8 -*-
"""Draft 2020-12 JSON Schemas and Pure Standard Library Schema Validator.

Provides complete JSON Schema specifications for all Job and IPC DTOs with
zero external unpinned dependencies.
"""

from __future__ import annotations

import math
from typing import Any


class ValidationError(ValueError):
	"""Raised when a dictionary payload fails schema validation."""

	def __init__(self, errors: list[str]) -> None:
		message = "; ".join(errors) if errors else "Schema validation failed"
		super().__init__(message)
		self.errors = errors


# ---------------------------------------------------------------------------
# Authoritative Draft 2020-12 JSON Schema Definitions
# ---------------------------------------------------------------------------

HANDSHAKE_REQUEST_SCHEMA: dict[str, Any] = {
	"$schema": "https://json-schema.org/draft/2020-12/schema",
	"title": "HandshakeRequest",
	"type": "object",
	"required": [
		"type",
		"protocol_version",
		"client_name",
		"client_version",
		"client_pid",
		"supported_schemas",
		"requested_capabilities",
		"request_id",
	],
	"properties": {
		"type": {"const": "handshake_request"},
		"protocol_version": {"type": "string"},
		"client_name": {"type": "string"},
		"client_version": {"type": "string"},
		"client_pid": {"type": "integer"},
		"supported_schemas": {
			"type": "array",
			"items": {"type": "string"},
		},
		"requested_capabilities": {
			"type": "array",
			"items": {"type": "string"},
		},
		"request_id": {"type": "string"},
	},
	"additionalProperties": False,
}

HANDSHAKE_RESPONSE_SCHEMA: dict[str, Any] = {
	"$schema": "https://json-schema.org/draft/2020-12/schema",
	"title": "HandshakeResponse",
	"type": "object",
	"required": [
		"type",
		"accepted",
		"protocol_version",
		"worker_pid",
		"worker_version",
		"negotiated_capabilities",
		"max_frame_bytes",
		"error_message",
		"correlation_id",
	],
	"properties": {
		"type": {"const": "handshake_response"},
		"accepted": {"type": "boolean"},
		"protocol_version": {"type": "string"},
		"worker_pid": {"type": "integer"},
		"worker_version": {"type": "string"},
		"negotiated_capabilities": {
			"type": "array",
			"items": {"type": "string"},
		},
		"max_frame_bytes": {"type": "integer", "minimum": 1},
		"error_message": {"type": ["string", "null"]},
		"correlation_id": {"type": "string"},
	},
	"additionalProperties": False,
}

JOB_SPEC_SCHEMA: dict[str, Any] = {
	"$schema": "https://json-schema.org/draft/2020-12/schema",
	"title": "JobSpec",
	"type": "object",
	"required": [
		"type",
		"job_id",
		"job_type",
		"payload",
		"priority",
		"timeout_seconds",
		"generation",
		"created_at_epoch_ms",
	],
	"properties": {
		"type": {"const": "job_submission"},
		"job_id": {"type": "string"},
		"job_type": {"type": "string"},
		"payload": {"type": "object"},
		"priority": {"type": "integer"},
		"timeout_seconds": {"type": "number", "minimum": 0.0},
		"generation": {"type": "integer", "minimum": 1},
		"created_at_epoch_ms": {"type": "integer", "minimum": 0},
	},
	"additionalProperties": False,
}

JOB_SUBMISSION_SCHEMA = JOB_SPEC_SCHEMA

JOB_PROGRESS_SCHEMA: dict[str, Any] = {
	"$schema": "https://json-schema.org/draft/2020-12/schema",
	"title": "JobProgress",
	"type": "object",
	"required": [
		"type",
		"job_id",
		"status",
		"progress_pct",
		"status_message",
		"bytes_completed",
		"bytes_total",
		"throughput_bytes_per_sec",
		"eta_seconds",
		"generation",
		"timestamp_epoch_ms",
	],
	"properties": {
		"type": {"const": "job_update"},
		"job_id": {"type": "string"},
		"status": {
			"enum": ["submitted", "queued", "running", "completed", "failed", "cancelled"],
		},
		"progress_pct": {"type": "number", "minimum": 0.0, "maximum": 100.0},
		"status_message": {"type": "string"},
		"bytes_completed": {"type": "integer", "minimum": 0},
		"bytes_total": {"type": "integer", "minimum": 0},
		"throughput_bytes_per_sec": {"type": "number", "minimum": 0.0},
		"eta_seconds": {"type": ["number", "null"], "minimum": 0.0},
		"generation": {"type": "integer", "minimum": 1},
		"timestamp_epoch_ms": {"type": "integer", "minimum": 0},
	},
	"additionalProperties": False,
}

JOB_UPDATE_SCHEMA = JOB_PROGRESS_SCHEMA

JOB_RESULT_SCHEMA: dict[str, Any] = {
	"$schema": "https://json-schema.org/draft/2020-12/schema",
	"title": "JobResult",
	"type": "object",
	"required": [
		"type",
		"job_id",
		"status",
		"result_data",
		"error_code",
		"error_message",
		"retriable",
		"duration_ms",
		"generation",
	],
	"properties": {
		"type": {"const": "job_result"},
		"job_id": {"type": "string"},
		"status": {
			"enum": ["completed", "failed", "cancelled"],
		},
		"result_data": {"type": "object"},
		"error_code": {"type": ["string", "null"]},
		"error_message": {"type": ["string", "null"]},
		"retriable": {"type": "boolean"},
		"duration_ms": {"type": "integer", "minimum": 0},
		"generation": {"type": "integer", "minimum": 1},
	},
	"additionalProperties": False,
}

JOB_CANCELLATION_REQUEST_SCHEMA: dict[str, Any] = {
	"$schema": "https://json-schema.org/draft/2020-12/schema",
	"title": "JobCancellationRequest",
	"type": "object",
	"required": [
		"type",
		"job_id",
		"reason",
		"preemption_timeout_seconds",
		"generation",
	],
	"properties": {
		"type": {"const": "job_cancellation_request"},
		"job_id": {"type": "string"},
		"reason": {"type": "string"},
		"preemption_timeout_seconds": {"type": "number", "minimum": 0.0},
		"generation": {"type": "integer", "minimum": 1},
	},
	"additionalProperties": False,
}

SESSION_CONFIG_SCHEMA: dict[str, Any] = {
	"$schema": "https://json-schema.org/draft/2020-12/schema",
	"title": "SessionConfig",
	"type": "object",
	"required": [
		"type",
		"session_id",
		"modality",
		"config_parameters",
		"max_queue_depth",
		"buffer_capacity_ms",
		"generation",
	],
	"properties": {
		"type": {"const": "session_config"},
		"session_id": {"type": "string"},
		"modality": {
			"enum": ["download", "inference", "ocr", "transcription", "embedding", "tts"],
		},
		"config_parameters": {"type": "object"},
		"max_queue_depth": {"type": "integer", "minimum": 1},
		"buffer_capacity_ms": {"type": "integer", "minimum": 1},
		"generation": {"type": "integer", "minimum": 1},
	},
	"additionalProperties": False,
}

STREAM_CHUNK_SCHEMA: dict[str, Any] = {
	"$schema": "https://json-schema.org/draft/2020-12/schema",
	"title": "StreamChunk",
	"type": "object",
	"required": [
		"type",
		"session_id",
		"sequence_number",
		"is_partial",
		"payload_text",
		"start_ms",
		"end_ms",
		"confidence",
		"bounding_boxes",
		"dropped_frames_count",
		"generation",
	],
	"properties": {
		"type": {"const": "stream_chunk"},
		"session_id": {"type": "string"},
		"sequence_number": {"type": "integer", "minimum": 0},
		"is_partial": {"type": "boolean"},
		"payload_text": {"type": "string"},
		"start_ms": {"type": "integer", "minimum": 0},
		"end_ms": {"type": "integer", "minimum": 0},
		"confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
		"bounding_boxes": {
			"type": "array",
			"items": {"type": "object"},
		},
		"dropped_frames_count": {"type": "integer", "minimum": 0},
		"generation": {"type": "integer", "minimum": 1},
	},
	"additionalProperties": False,
}

WORKER_HEALTH_SCHEMA: dict[str, Any] = {
	"$schema": "https://json-schema.org/draft/2020-12/schema",
	"title": "WorkerHealth",
	"type": "object",
	"required": [
		"type",
		"worker_pid",
		"generation",
		"uptime_seconds",
		"active_jobs_count",
		"active_sessions_count",
		"cpu_percent",
		"rss_memory_bytes",
		"gpu_available",
		"gpu_memory_used_bytes",
		"gpu_memory_total_bytes",
		"is_healthy",
		"error_summary",
	],
	"properties": {
		"type": {"const": "worker_health"},
		"worker_pid": {"type": "integer"},
		"generation": {"type": "integer", "minimum": 1},
		"uptime_seconds": {"type": "number", "minimum": 0.0},
		"active_jobs_count": {"type": "integer", "minimum": 0},
		"active_sessions_count": {"type": "integer", "minimum": 0},
		"cpu_percent": {"type": "number", "minimum": 0.0},
		"rss_memory_bytes": {"type": "integer", "minimum": 0},
		"gpu_available": {"type": "boolean"},
		"gpu_memory_used_bytes": {"type": "integer", "minimum": 0},
		"gpu_memory_total_bytes": {"type": "integer", "minimum": 0},
		"is_healthy": {"type": "boolean"},
		"error_summary": {"type": ["string", "null"]},
	},
	"additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Pure Standard Library Schema Validator (Zero Unpinned Dependencies)
# ---------------------------------------------------------------------------


def _matches_type(val: Any, expected: str) -> bool:
	"""Check whether val matches JSON Schema primitive type."""
	if expected == "null":
		return val is None
	if expected == "boolean":
		return isinstance(val, bool)
	if expected == "integer":
		return isinstance(val, int) and not isinstance(val, bool)
	if expected == "number":
		return (isinstance(val, (int, float)) and not isinstance(val, bool))
	if expected == "string":
		return isinstance(val, str)
	if expected == "array":
		return isinstance(val, (list, tuple))
	if expected == "object":
		return isinstance(val, dict)
	return False


def _collect_errors(instance: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
	"""Recursively validate instance against schema and collect error messages."""
	errors: list[str] = []

	# Check 'type'
	expected_type = schema.get("type")
	if expected_type is not None:
		if isinstance(expected_type, list):
			if not any(_matches_type(instance, t) for t in expected_type):
				type_names = ", ".join(expected_type)
				errors.append(
					f"{path}: expected one of types [{type_names}], got '{type(instance).__name__}'"
				)
				return errors
		elif isinstance(expected_type, str):
			if not _matches_type(instance, expected_type):
				errors.append(
					f"{path}: expected type '{expected_type}', got '{type(instance).__name__}'"
				)
				return errors

	# Check 'const'
	if "const" in schema and instance != schema["const"]:
		errors.append(f"{path}: expected const '{schema['const']}', got '{instance}'")

	# Check 'enum'
	if "enum" in schema and instance not in schema["enum"]:
		errors.append(f"{path}: value '{instance}' not in allowed enum {schema['enum']}")

	# Numerical range checks
	if isinstance(instance, (int, float)) and not isinstance(instance, bool):
		has_range = any(
			k in schema
			for k in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum")
		)
		if has_range and isinstance(instance, float) and (math.isnan(instance) or math.isinf(instance)):
			errors.append(f"{path}: non-finite number '{instance}' is not permitted in numeric range checks")
		else:
			if "minimum" in schema and instance < schema["minimum"]:
				errors.append(f"{path}: {instance} is less than minimum {schema['minimum']}")
			if "maximum" in schema and instance > schema["maximum"]:
				errors.append(f"{path}: {instance} is greater than maximum {schema['maximum']}")
			if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
				errors.append(f"{path}: {instance} must be strictly greater than {schema['exclusiveMinimum']}")
			if "exclusiveMaximum" in schema and instance >= schema["exclusiveMaximum"]:
				errors.append(f"{path}: {instance} must be strictly less than {schema['exclusiveMaximum']}")

	# String length checks
	if isinstance(instance, str):
		if "minLength" in schema and len(instance) < schema["minLength"]:
			errors.append(f"{path}: length {len(instance)} is less than minLength {schema['minLength']}")
		if "maxLength" in schema and len(instance) > schema["maxLength"]:
			errors.append(f"{path}: length {len(instance)} exceeds maxLength {schema['maxLength']}")

	# Object checks
	if isinstance(instance, dict):
		# Check 'required'
		for req_prop in schema.get("required", ()):
			if req_prop not in instance:
				errors.append(f"{path}: missing required property '{req_prop}'")

		# Check properties and additionalProperties
		properties = schema.get("properties", {})
		for key, val in instance.items():
			if key in properties:
				errors.extend(_collect_errors(val, properties[key], path=f"{path}.{key}"))
			elif schema.get("additionalProperties") is False:
				errors.append(f"{path}: unexpected additional property '{key}'")

	# Array checks
	elif isinstance(instance, (list, tuple)):
		if "minItems" in schema and len(instance) < schema["minItems"]:
			errors.append(f"{path}: item count {len(instance)} is less than minItems {schema['minItems']}")
		if "maxItems" in schema and len(instance) > schema["maxItems"]:
			errors.append(f"{path}: item count {len(instance)} exceeds maxItems {schema['maxItems']}")

		item_schema = schema.get("items")
		if item_schema and isinstance(item_schema, dict):
			for idx, item in enumerate(instance):
				errors.extend(_collect_errors(item, item_schema, path=f"{path}[{idx}]"))

	return errors


def validate_schema(data: Any, schema: dict[str, Any], path: str = "$") -> None:
	"""Validate an in-memory dictionary data structure against a JSON schema dictionary.

	Raises:
		ValidationError: if the data does not conform to the schema.
	"""
	errors = _collect_errors(data, schema, path=path)
	if errors:
		raise ValidationError(errors)
