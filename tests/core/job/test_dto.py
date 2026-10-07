# -*- coding: utf-8 -*-
"""Unit tests for immutable Job and IPC DTOs (Invariant A24)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
import unittest

from tests.support import load_addon_module

dto_mod = load_addon_module("core.job.dto")

HandshakeRequest = dto_mod.HandshakeRequest
HandshakeResponse = dto_mod.HandshakeResponse
JobCancellationRequest = dto_mod.JobCancellationRequest
JobFailure = dto_mod.JobFailure
JobProgress = dto_mod.JobProgress
JobResult = dto_mod.JobResult
JobSnapshot = dto_mod.JobSnapshot
JobSpec = dto_mod.JobSpec
JobState = dto_mod.JobState
JobStatus = dto_mod.JobStatus
JobSubmission = dto_mod.JobSubmission
JobUpdate = dto_mod.JobUpdate
ModalityType = dto_mod.ModalityType
SessionConfig = dto_mod.SessionConfig
SessionState = dto_mod.SessionState
StreamChunk = dto_mod.StreamChunk
WorkerHealth = dto_mod.WorkerHealth


class TestJobDTOImmutabilityAndSlots(unittest.TestCase):
	"""Verify frozen dataclass immutability, slots, and memory optimization."""

	def test_job_status_enum(self) -> None:
		self.assertIs(JobStatus, JobState)
		self.assertEqual(JobStatus.SUBMITTED, "submitted")
		self.assertEqual(JobStatus.QUEUED, "queued")
		self.assertEqual(JobStatus.RUNNING, "running")
		self.assertEqual(JobStatus.COMPLETED, "completed")
		self.assertEqual(JobStatus.FAILED, "failed")
		self.assertEqual(JobStatus.CANCELLED, "cancelled")

		self.assertTrue(JobStatus.COMPLETED.is_terminal)
		self.assertTrue(JobStatus.FAILED.is_terminal)
		self.assertTrue(JobStatus.CANCELLED.is_terminal)
		self.assertFalse(JobStatus.RUNNING.is_terminal)
		self.assertFalse(JobStatus.QUEUED.is_terminal)
		self.assertFalse(JobStatus.SUBMITTED.is_terminal)

		self.assertTrue(JobStatus.SUBMITTED.is_active)
		self.assertTrue(JobStatus.QUEUED.is_active)
		self.assertTrue(JobStatus.RUNNING.is_active)
		self.assertFalse(JobStatus.COMPLETED.is_active)

	def test_session_state_enum(self) -> None:
		self.assertEqual(SessionState.INIT, "init")
		self.assertEqual(SessionState.STREAMING, "streaming")
		self.assertTrue(SessionState.CLOSED.is_terminal)
		self.assertTrue(SessionState.ERROR.is_terminal)
		self.assertFalse(SessionState.STREAMING.is_terminal)
		self.assertTrue(SessionState.READY.is_active)
		self.assertTrue(SessionState.STREAMING.is_active)
		self.assertTrue(SessionState.PAUSED.is_active)

	def test_modality_type_enum(self) -> None:
		self.assertEqual(ModalityType.DOWNLOAD, "download")
		self.assertEqual(ModalityType.INFERENCE, "inference")
		self.assertEqual(ModalityType.OCR, "ocr")
		self.assertEqual(ModalityType.TRANSCRIPTION, "transcription")
		self.assertEqual(ModalityType.EMBEDDING, "embedding")
		self.assertEqual(ModalityType.TTS, "tts")

	def test_job_spec_immutability_and_slots(self) -> None:
		spec = JobSpec(job_id="j1", job_type="download", payload={"url": "http://example.com"})
		self.assertFalse(hasattr(spec, "__dict__"))
		with self.assertRaises(FrozenInstanceError):
			spec.job_id = "j2"  # type: ignore[misc]

	def test_job_progress_immutability_and_slots(self) -> None:
		progress = JobProgress(job_id="j1", status=JobStatus.RUNNING, progress_pct=50.0)
		self.assertFalse(hasattr(progress, "__dict__"))
		with self.assertRaises(FrozenInstanceError):
			progress.progress_pct = 75.0  # type: ignore[misc]

	def test_job_result_immutability_and_slots(self) -> None:
		result = JobResult(job_id="j1", status=JobStatus.COMPLETED, result_data={"ok": True})
		self.assertFalse(hasattr(result, "__dict__"))
		with self.assertRaises(FrozenInstanceError):
			result.status = JobStatus.FAILED  # type: ignore[misc]

	def test_job_result_requires_terminal_status(self) -> None:
		with self.assertRaises(ValueError):
			JobResult(job_id="j1", status=JobStatus.RUNNING)
		with self.assertRaises(ValueError):
			JobResult(job_id="j1", status=JobStatus.SUBMITTED)

	def test_job_failure_immutability(self) -> None:
		failure = JobFailure(error_code="ERR", error_message="msg", retriable=True)
		self.assertFalse(hasattr(failure, "__dict__"))
		with self.assertRaises(FrozenInstanceError):
			failure.error_code = "ERR2"  # type: ignore[misc]

	def test_handshake_request_immutability_and_tuples(self) -> None:
		req = HandshakeRequest(client_pid=123)
		self.assertFalse(hasattr(req, "__dict__"))
		self.assertIsInstance(req.supported_schemas, tuple)
		self.assertIsInstance(req.requested_capabilities, tuple)
		with self.assertRaises(FrozenInstanceError):
			req.client_pid = 456  # type: ignore[misc]

	def test_handshake_response_immutability_and_tuples(self) -> None:
		resp = HandshakeResponse(
			accepted=True,
			protocol_version="1.0.0",
			worker_pid=1234,
			worker_version="1.0.0",
			negotiated_capabilities=("job.inference",),
		)
		self.assertFalse(hasattr(resp, "__dict__"))
		self.assertIsInstance(resp.negotiated_capabilities, tuple)
		with self.assertRaises(FrozenInstanceError):
			resp.accepted = False  # type: ignore[misc]


class TestJobDTOSerializationRoundTrip(unittest.TestCase):
	"""Verify dictionary and JSON round-tripping for all DTOs."""

	def test_handshake_request_round_trip(self) -> None:
		req1 = HandshakeRequest(
			protocol_version="1.0.0",
			client_name="test_client",
			client_version="1.2.3",
			client_pid=999,
			supported_schemas=("job.v1", "custom.v1"),
			requested_capabilities=("cap.a", "cap.b"),
			request_id="req-uuid-1",
		)
		d = req1.to_dict()
		self.assertEqual(d["type"], "handshake_request")
		self.assertEqual(d["client_name"], "test_client")
		self.assertEqual(d["supported_schemas"], ["job.v1", "custom.v1"])

		s = req1.to_json()
		req2 = HandshakeRequest.from_json(s)
		self.assertEqual(req1, req2)
		self.assertIsInstance(req2.supported_schemas, tuple)

	def test_handshake_response_round_trip(self) -> None:
		resp1 = HandshakeResponse(
			accepted=True,
			protocol_version="1.0.0",
			worker_pid=54321,
			worker_version="1.0.0",
			negotiated_capabilities=("job.model_download",),
			error_message=None,
			correlation_id="corr-1",
		)
		d = resp1.to_dict()
		self.assertEqual(d["type"], "handshake_response")
		self.assertTrue(d["accepted"])
		self.assertIsNone(d["error_message"])

		s = resp1.to_json()
		resp2 = HandshakeResponse.from_json(s)
		self.assertEqual(resp1, resp2)
		self.assertIsInstance(resp2.negotiated_capabilities, tuple)

	def test_job_spec_round_trip(self) -> None:
		spec1 = JobSpec(
			job_id="job_001",
			job_type="model_download",
			payload={"repo_id": "google/gemma-2b", "revision": "main"},
			priority=5,
			timeout_seconds=60.0,
			generation=2,
			created_at_epoch_ms=1700000000000,
		)
		d = spec1.to_dict()
		self.assertEqual(d["type"], "job_submission")
		self.assertEqual(d["job_id"], "job_001")
		self.assertEqual(d["priority"], 5)

		s = spec1.to_json()
		spec2 = JobSubmission.from_json(s)
		self.assertEqual(spec1, spec2)

	def test_job_progress_round_trip(self) -> None:
		prog1 = JobProgress(
			job_id="job_001",
			status=JobStatus.RUNNING,
			progress_pct=42.567,
			status_message="Downloading weights...",
			bytes_completed=1000,
			bytes_total=2000,
			throughput_bytes_per_sec=500.25,
			eta_seconds=2.0,
			generation=2,
			timestamp_epoch_ms=1700000001000,
		)
		d = prog1.to_dict()
		self.assertEqual(d["type"], "job_update")
		self.assertEqual(d["progress_pct"], 42.57)
		self.assertEqual(d["status"], "running")

		s = prog1.to_json()
		prog2 = JobUpdate.from_json(s)
		self.assertEqual(prog2.job_id, "job_001")
		self.assertEqual(prog2.status, JobStatus.RUNNING)
		self.assertAlmostEqual(prog2.progress_pct, 42.57, places=2)
		self.assertEqual(prog2.bytes_completed, 1000)

	def test_job_result_round_trip(self) -> None:
		res1 = JobResult(
			job_id="job_001",
			status=JobStatus.COMPLETED,
			result_data={"model_path": "C:\\models\\test"},
			duration_ms=450,
			generation=2,
		)
		d = res1.to_dict()
		self.assertEqual(d["type"], "job_result")
		self.assertEqual(d["status"], "completed")

		s = res1.to_json()
		res2 = JobResult.from_json(s)
		self.assertEqual(res1, res2)

	def test_job_failure_round_trip(self) -> None:
		fail1 = JobFailure(
			error_code="CHECKSUM_MISMATCH",
			error_message="Hash did not match",
			retriable=False,
			details={"expected": "abc", "actual": "def"},
			traceback_summary="Traceback at download.py:42",
		)
		d = fail1.to_dict()
		self.assertEqual(d["error_code"], "CHECKSUM_MISMATCH")
		fail2 = JobFailure.from_dict(d)
		self.assertEqual(fail1, fail2)

	def test_job_snapshot_round_trip(self) -> None:
		spec = JobSpec(job_id="j1", job_type="inference", payload={"prompt": "hi"})
		progress = JobProgress(job_id="j1", status=JobStatus.RUNNING, progress_pct=10.0)
		result = JobResult(job_id="j1", status=JobStatus.COMPLETED, result_data={"out": "hey"})
		snap1 = JobSnapshot(
			spec=spec,
			state=JobStatus.COMPLETED,
			progress=progress,
			result=result,
			created_at_epoch_ms=100,
			updated_at_epoch_ms=200,
		)
		self.assertEqual(snap1.job_id, "j1")
		self.assertTrue(snap1.is_terminal)
		self.assertTrue(snap1.is_success)

		d = snap1.to_dict()
		snap2 = JobSnapshot.from_dict(d)
		self.assertEqual(snap1, snap2)

		s = snap1.to_json()
		snap3 = JobSnapshot.from_json(s)
		self.assertEqual(snap1, snap3)

	def test_job_cancellation_request_round_trip(self) -> None:
		req1 = JobCancellationRequest(job_id="j1", reason="user requested cancel", preemption_timeout_seconds=5.0)
		d = req1.to_dict()
		self.assertEqual(d["type"], "job_cancellation_request")
		self.assertEqual(d["job_id"], "j1")
		req2 = JobCancellationRequest.from_json(json.dumps(d))
		self.assertEqual(req1, req2)

	def test_session_config_round_trip(self) -> None:
		cfg1 = SessionConfig(
			session_id="sess_01",
			modality=ModalityType.OCR,
			config_parameters={"fps": 5},
			max_queue_depth=3,
			buffer_capacity_ms=5000,
			generation=1,
		)
		d = cfg1.to_dict()
		self.assertEqual(d["type"], "session_config")
		self.assertEqual(d["modality"], "ocr")
		cfg2 = SessionConfig.from_dict(d)
		self.assertEqual(cfg1, cfg2)

	def test_stream_chunk_round_trip(self) -> None:
		chunk1 = StreamChunk(
			session_id="sess_01",
			sequence_number=14,
			is_partial=True,
			payload_text="Recognized Text",
			start_ms=100,
			end_ms=250,
			confidence=0.98765,
			bounding_boxes=({"x": 10, "y": 20, "w": 30, "h": 40},),
			dropped_frames_count=1,
			generation=1,
		)
		d = chunk1.to_dict()
		self.assertEqual(d["type"], "stream_chunk")
		self.assertEqual(d["confidence"], 0.9877)
		chunk2 = StreamChunk.from_dict(d)
		self.assertEqual(chunk2.sequence_number, 14)
		self.assertEqual(chunk2.payload_text, "Recognized Text")
		self.assertEqual(len(chunk2.bounding_boxes), 1)
		self.assertIsInstance(chunk2.bounding_boxes, tuple)

	def test_worker_health_round_trip(self) -> None:
		health1 = WorkerHealth(
			worker_pid=9876,
			generation=3,
			uptime_seconds=3600.5,
			active_jobs_count=2,
			active_sessions_count=1,
			cpu_percent=12.4,
			rss_memory_bytes=104857600,
			gpu_available=True,
			gpu_memory_used_bytes=1000,
			gpu_memory_total_bytes=8000,
			is_healthy=True,
			error_summary=None,
		)
		d = health1.to_dict()
		self.assertEqual(d["type"], "worker_health")
		self.assertEqual(d["worker_pid"], 9876)
		health2 = WorkerHealth.from_dict(d)
		self.assertEqual(health1, health2)


if __name__ == "__main__":
	unittest.main()
