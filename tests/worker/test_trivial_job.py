# -*- coding: utf-8 -*-
"""Unit tests for End-to-End Trivial Jobs, Progress Streaming, and Cancellation (Invariants A18, A21, A22)."""

from __future__ import annotations

import unittest
import uuid

from tests.support import load_addon_module

dto_mod = load_addon_module("core.job.dto")
sup_mod = load_addon_module("plugin.worker_supervisor")
worker_client_mod = load_addon_module("service.worker_client")

JobProgress = dto_mod.JobProgress
JobResult = dto_mod.JobResult
JobSpec = dto_mod.JobSpec
JobStatus = dto_mod.JobStatus
NamedPipeWorkerClient = worker_client_mod.NamedPipeWorkerClient
WorkerSupervisor = sup_mod.WorkerSupervisor


class TestTrivialJobs(unittest.TestCase):
	"""Verify end-to-end execution of Echo and Trivial Compute jobs across Named Pipes."""

	def setUp(self) -> None:
		token = uuid.uuid4().hex[:8]
		self.cmd_pipe = f"\\\\.\\pipe\\test_trivial_cmd_{token}"
		self.evt_pipe = f"\\\\.\\pipe\\test_trivial_evt_{token}"

		self.supervisor = WorkerSupervisor(
			cmd_pipe_name=self.cmd_pipe,
			evt_pipe_name=self.evt_pipe,
			auto_restart=False,
		)
		self.assertTrue(self.supervisor.start(auto_connect_pipes=False))

		self.worker_client = NamedPipeWorkerClient(
			cmd_pipe_name=self.cmd_pipe,
			evt_pipe_name=self.evt_pipe,
		)
		self.worker_client.connect()
		self.job_client = self.worker_client.get_job_client()

	def tearDown(self) -> None:
		self.worker_client.disconnect()
		self.supervisor.stop()

	def test_echo_job_execution(self) -> None:
		"""Verify submitting echo job returns completed result with echoed payload."""
		spec = JobSpec(
			job_id="echo-001",
			job_type="echo",
			payload={"message": "hello NVDA"},
		)
		job_id = self.job_client.submit_job(spec)
		self.assertEqual(job_id, "echo-001")

		result = self.job_client.wait_for_job(job_id, timeout_seconds=3.0)
		self.assertEqual(result.status, JobStatus.COMPLETED)
		self.assertEqual(result.result_data.get("echo"), "hello NVDA")

		# Verify snapshot
		snap = self.job_client.get_job_snapshot(job_id)
		self.assertIsNotNone(snap)
		self.assertEqual(snap.state, JobStatus.COMPLETED)

	def test_trivial_compute_progress_streaming(self) -> None:
		"""Verify multi-step compute job streams JobProgress updates across event pipe."""
		progress_updates: list[float] = []

		def on_progress(p: JobProgress) -> None:
			progress_updates.append(p.progress_pct)

		spec = JobSpec(
			job_id="compute-001",
			job_type="trivial_compute",
			payload={"steps": 4, "step_delay": 0.02},
		)

		self.job_client.subscribe_progress("compute-001", on_progress)
		job_id = self.job_client.submit_job(spec)
		self.assertEqual(job_id, "compute-001")

		result = self.job_client.wait_for_job(job_id, timeout_seconds=3.0)
		self.assertEqual(result.status, JobStatus.COMPLETED)
		self.assertEqual(result.result_data.get("steps_completed"), 4)

		# Verify progressive updates were emitted
		self.assertGreaterEqual(len(progress_updates), 2)
		self.assertTrue(all(p > 0 for p in progress_updates))

	def test_cooperative_cancellation_at_yield_points(self) -> None:
		"""Verify job yields promptly when cooperative cancellation is requested (Invariant A22)."""
		spec = JobSpec(
			job_id="cancel-001",
			job_type="trivial_compute",
			payload={"steps": 50, "step_delay": 0.03},
		)

		self.job_client.submit_job(spec)

		# Wait for at least one step to start, then cancel
		cancelled = self.job_client.cancel_job("cancel-001", reason="user_stop")
		self.assertTrue(cancelled)

		result = self.job_client.wait_for_job("cancel-001", timeout_seconds=2.0)
		self.assertEqual(result.status, JobStatus.CANCELLED)
		self.assertIn("cancelled_at_step", result.result_data)


if __name__ == "__main__":
	unittest.main()
