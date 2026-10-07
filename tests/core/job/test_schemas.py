# -*- coding: utf-8 -*-
"""Unit tests for JSON Schemas and Pure-Python Schema Validator (Draft 2020-12)."""

from __future__ import annotations

import unittest

from tests.support import load_addon_module

dto_mod = load_addon_module("core.job.dto")
schemas_mod = load_addon_module("core.job.schemas")

HandshakeRequest = dto_mod.HandshakeRequest
HandshakeResponse = dto_mod.HandshakeResponse
JobCancellationRequest = dto_mod.JobCancellationRequest
JobProgress = dto_mod.JobProgress
JobResult = dto_mod.JobResult
JobSpec = dto_mod.JobSpec
JobStatus = dto_mod.JobStatus
ModalityType = dto_mod.ModalityType
SessionConfig = dto_mod.SessionConfig
StreamChunk = dto_mod.StreamChunk
WorkerHealth = dto_mod.WorkerHealth

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

ALL_SCHEMAS = (
	HANDSHAKE_REQUEST_SCHEMA,
	HANDSHAKE_RESPONSE_SCHEMA,
	JOB_SPEC_SCHEMA,
	JOB_PROGRESS_SCHEMA,
	JOB_RESULT_SCHEMA,
	JOB_CANCELLATION_REQUEST_SCHEMA,
	SESSION_CONFIG_SCHEMA,
	STREAM_CHUNK_SCHEMA,
	WORKER_HEALTH_SCHEMA,
)


class TestSchemaValidationPositive(unittest.TestCase):
	"""Verify all valid DTO wire dictionaries pass schema validation cleanly."""

	def test_handshake_request_schema_valid(self) -> None:
		req = HandshakeRequest(client_pid=123)
		validate_schema(req.to_dict(), HANDSHAKE_REQUEST_SCHEMA)

	def test_handshake_response_schema_valid(self) -> None:
		resp = HandshakeResponse(
			accepted=True,
			protocol_version="1.0.0",
			worker_pid=999,
			worker_version="1.0.0",
			negotiated_capabilities=("job.inference",),
		)
		validate_schema(resp.to_dict(), HANDSHAKE_RESPONSE_SCHEMA)

	def test_job_spec_schema_valid(self) -> None:
		spec = JobSpec(job_id="j1", job_type="download", payload={"url": "http://example.com"})
		validate_schema(spec.to_dict(), JOB_SPEC_SCHEMA)

	def test_job_progress_schema_valid(self) -> None:
		prog = JobProgress(job_id="j1", status=JobStatus.RUNNING, progress_pct=55.5)
		validate_schema(prog.to_dict(), JOB_PROGRESS_SCHEMA)

	def test_job_result_schema_valid(self) -> None:
		res = JobResult(job_id="j1", status=JobStatus.COMPLETED, result_data={"ok": True})
		validate_schema(res.to_dict(), JOB_RESULT_SCHEMA)

	def test_job_cancellation_request_schema_valid(self) -> None:
		req = JobCancellationRequest(job_id="j1", reason="abort")
		validate_schema(req.to_dict(), JOB_CANCELLATION_REQUEST_SCHEMA)

	def test_session_config_schema_valid(self) -> None:
		cfg = SessionConfig(session_id="s1", modality=ModalityType.OCR)
		validate_schema(cfg.to_dict(), SESSION_CONFIG_SCHEMA)

	def test_stream_chunk_schema_valid(self) -> None:
		chunk = StreamChunk(
			session_id="s1",
			sequence_number=1,
			is_partial=False,
			payload_text="hello",
			bounding_boxes=({"x": 1, "y": 2},),
		)
		validate_schema(chunk.to_dict(), STREAM_CHUNK_SCHEMA)

	def test_worker_health_schema_valid(self) -> None:
		health = WorkerHealth(
			worker_pid=1234,
			generation=1,
			uptime_seconds=10.0,
			active_jobs_count=0,
			active_sessions_count=0,
			cpu_percent=1.0,
			rss_memory_bytes=1000,
		)
		validate_schema(health.to_dict(), WORKER_HEALTH_SCHEMA)


class TestSchemaValidationNegative(unittest.TestCase):
	"""Verify schema validator catches property, type, enum, const, and range violations."""

	def test_missing_required_property(self) -> None:
		spec = JobSpec(job_id="j1", job_type="download").to_dict()
		del spec["job_id"]
		with self.assertRaises(ValidationError) as ctx:
			validate_schema(spec, JOB_SPEC_SCHEMA)
		self.assertIn("missing required property 'job_id'", str(ctx.exception))

	def test_unexpected_additional_property(self) -> None:
		spec = JobSpec(job_id="j1", job_type="download").to_dict()
		spec["extra_unexpected_field"] = "bad"
		with self.assertRaises(ValidationError) as ctx:
			validate_schema(spec, JOB_SPEC_SCHEMA)
		self.assertIn("unexpected additional property 'extra_unexpected_field'", str(ctx.exception))

	def test_const_type_mismatch(self) -> None:
		spec = JobSpec(job_id="j1", job_type="download").to_dict()
		spec["type"] = "invalid_message_type"
		with self.assertRaises(ValidationError) as ctx:
			validate_schema(spec, JOB_SPEC_SCHEMA)
		self.assertIn("expected const 'job_submission'", str(ctx.exception))

	def test_enum_value_mismatch(self) -> None:
		prog = JobProgress(job_id="j1", status=JobStatus.RUNNING).to_dict()
		prog["status"] = "sleeping"
		with self.assertRaises(ValidationError) as ctx:
			validate_schema(prog, JOB_PROGRESS_SCHEMA)
		self.assertIn("not in allowed enum", str(ctx.exception))

	def test_type_mismatch_boolean_not_integer(self) -> None:
		spec = JobSpec(job_id="j1", job_type="download").to_dict()
		spec["priority"] = True  # booleans should not validate as integer
		with self.assertRaises(ValidationError) as ctx:
			validate_schema(spec, JOB_SPEC_SCHEMA)
		self.assertIn("expected type 'integer', got 'bool'", str(ctx.exception))

	def test_type_mismatch_string_not_number(self) -> None:
		prog = JobProgress(job_id="j1", status=JobStatus.RUNNING).to_dict()
		prog["progress_pct"] = "fifty"
		with self.assertRaises(ValidationError) as ctx:
			validate_schema(prog, JOB_PROGRESS_SCHEMA)
		self.assertIn("expected type 'number'", str(ctx.exception))

	def test_numerical_range_minimum_violation(self) -> None:
		prog = JobProgress(job_id="j1", status=JobStatus.RUNNING).to_dict()
		prog["progress_pct"] = -5.0
		with self.assertRaises(ValidationError) as ctx:
			validate_schema(prog, JOB_PROGRESS_SCHEMA)
		self.assertIn("is less than minimum", str(ctx.exception))

	def test_numerical_range_maximum_violation(self) -> None:
		prog = JobProgress(job_id="j1", status=JobStatus.RUNNING).to_dict()
		prog["progress_pct"] = 150.0
		with self.assertRaises(ValidationError) as ctx:
			validate_schema(prog, JOB_PROGRESS_SCHEMA)
		self.assertIn("is greater than maximum", str(ctx.exception))

	def test_array_item_type_mismatch(self) -> None:
		req = HandshakeRequest(client_pid=123).to_dict()
		req["supported_schemas"] = [123, 456]  # items should be string
		with self.assertRaises(ValidationError) as ctx:
			validate_schema(req, HANDSHAKE_REQUEST_SCHEMA)
		self.assertIn("expected type 'string'", str(ctx.exception))

	def test_numerical_range_rejects_nan_and_inf(self) -> None:
		"""Verify that NaN and Inf are rejected by numerical range checks."""
		for special_val in (float("nan"), float("inf"), float("-inf")):
			prog = JobProgress(job_id="j1", status=JobStatus.RUNNING).to_dict()
			prog["progress_pct"] = special_val
			with self.assertRaises(ValidationError) as ctx:
				validate_schema(prog, JOB_PROGRESS_SCHEMA)
			self.assertIn("non-finite number", str(ctx.exception))


class TestDraft202012CrossValidation(unittest.TestCase):
	"""Cross-validate schemas with official jsonschema Draft202012Validator if available."""

	def test_schemas_conform_to_draft_202012_meta_schema(self) -> None:
		try:
			from jsonschema import Draft202012Validator
		except ImportError:
			self.skipTest("jsonschema library not installed in this environment")

		for schema in ALL_SCHEMAS:
			with self.subTest(schema_title=schema.get("title")):
				# Meta-schema check verifies the schema structure is valid Draft 2020-12
				Draft202012Validator.check_schema(schema)

	def test_cross_validation_agrees_with_jsonschema(self) -> None:
		try:
			from jsonschema import Draft202012Validator
		except ImportError:
			self.skipTest("jsonschema library not installed in this environment")

		# Valid payload check
		spec_dict = JobSpec(job_id="j1", job_type="inference").to_dict()
		validator = Draft202012Validator(JOB_SPEC_SCHEMA)
		self.assertTrue(validator.is_valid(spec_dict))

		# Invalid payload check (missing job_id)
		invalid_dict = dict(spec_dict)
		del invalid_dict["job_id"]
		self.assertFalse(validator.is_valid(invalid_dict))


if __name__ == "__main__":
	unittest.main()
