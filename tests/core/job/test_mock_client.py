# -*- coding: utf-8 -*-
"""Unit tests for MockJobClient and MockWorkerClient."""

from __future__ import annotations

import threading
import time
import unittest

from tests.support import load_addon_module

client_mod = load_addon_module("core.job.client")
dto_mod = load_addon_module("core.job.dto")

JobProgress = dto_mod.JobProgress
JobResult = dto_mod.JobResult
JobSpec = dto_mod.JobSpec
JobStatus = dto_mod.JobStatus

MockJobClient = client_mod.MockJobClient
MockWorkerClient = client_mod.MockWorkerClient


class TestMockJobClient(unittest.TestCase):
	"""Verify MockJobClient submission, progress tracking, cancellation, and execution."""

	def test_job_submission_and_snapshot(self) -> None:
		client = MockJobClient()
		spec = JobSpec(job_id="j-sub-1", job_type="inference", payload={"prompt": "test"})
		returned_id = client.submit_job(spec)

		self.assertEqual(returned_id, "j-sub-1")
		snap = client.get_job_snapshot("j-sub-1")
		self.assertIsNotNone(snap)
		self.assertEqual(snap.job_id, "j-sub-1")
		self.assertEqual(snap.state, JobStatus.SUBMITTED)
		self.assertFalse(snap.is_terminal)

		self.assertIsNone(client.get_job_snapshot("non-existent-job"))

	def test_list_active_jobs(self) -> None:
		client = MockJobClient()
		client.submit_job(JobSpec(job_id="j1", job_type="a"))
		client.submit_job(JobSpec(job_id="j2", job_type="b"))

		active = client.list_active_jobs()
		self.assertEqual(len(active), 2)

		client.simulate_complete("j1")
		active_after = client.list_active_jobs()
		self.assertEqual(len(active_after), 1)
		self.assertEqual(active_after[0].job_id, "j2")

	def test_progress_subscription_and_unsubscription(self) -> None:
		client = MockJobClient()
		client.submit_job(JobSpec(job_id="j-prog", job_type="download"))

		updates: list[JobProgress] = []
		unsub = client.subscribe_progress("j-prog", lambda p: updates.append(p))

		client.simulate_progress("j-prog", 25.0, "Quarter way")
		self.assertEqual(len(updates), 1)
		self.assertEqual(updates[0].progress_pct, 25.0)
		self.assertEqual(updates[0].status_message, "Quarter way")

		# Unsubscribe
		unsub()
		client.simulate_progress("j-prog", 50.0, "Half way")
		self.assertEqual(len(updates), 1)  # No new callback

	def test_result_subscription_and_immediate_fire_if_done(self) -> None:
		client = MockJobClient()
		client.submit_job(JobSpec(job_id="j-res", job_type="download"))

		results: list[JobResult] = []
		client.subscribe_result("j-res", lambda r: results.append(r))

		client.simulate_complete("j-res", result_data={"size": 1024})
		self.assertEqual(len(results), 1)
		self.assertEqual(results[0].status, JobStatus.COMPLETED)
		self.assertEqual(results[0].result_data["size"], 1024)

		# Subsequent subscriber on already completed job fires immediately
		late_results: list[JobResult] = []
		client.subscribe_result("j-res", lambda r: late_results.append(r))
		self.assertEqual(len(late_results), 1)
		self.assertEqual(late_results[0].status, JobStatus.COMPLETED)

	def test_simulate_failure(self) -> None:
		client = MockJobClient()
		client.submit_job(JobSpec(job_id="j-fail", job_type="verify"))

		results: list[JobResult] = []
		client.subscribe_result("j-fail", lambda r: results.append(r))

		client.simulate_failure("j-fail", error_code="CORRUPT", error_message="Hash check failed")
		self.assertEqual(len(results), 1)
		self.assertEqual(results[0].status, JobStatus.FAILED)
		self.assertEqual(results[0].error_code, "CORRUPT")
		self.assertEqual(results[0].error_message, "Hash check failed")

	def test_cancellation(self) -> None:
		client = MockJobClient()
		client.submit_job(JobSpec(job_id="j-cancel", job_type="long_run"))

		results: list[JobResult] = []
		client.subscribe_result("j-cancel", lambda r: results.append(r))

		self.assertTrue(client.cancel_job("j-cancel", reason="aborted by user"))
		self.assertEqual(len(results), 1)
		self.assertEqual(results[0].status, JobStatus.CANCELLED)
		self.assertEqual(results[0].error_message, "aborted by user")

		# Non-existent job cancel returns False
		self.assertFalse(client.cancel_job("missing-job"))

	def test_wait_for_job_success_and_timeout(self) -> None:
		client = MockJobClient()
		client.submit_job(JobSpec(job_id="j-async", job_type="compute"))

		def worker() -> None:
			time.sleep(0.05)
			client.simulate_complete("j-async", {"result": 42})

		thread = threading.Thread(target=worker)
		thread.start()

		res = client.wait_for_job("j-async", timeout_seconds=1.0)
		thread.join()
		self.assertEqual(res.status, JobStatus.COMPLETED)
		self.assertEqual(res.result_data["result"], 42)

		# Timeout test
		client.submit_job(JobSpec(job_id="j-slow", job_type="compute"))
		with self.assertRaises(TimeoutError):
			client.wait_for_job("j-slow", timeout_seconds=0.01)

		# Unknown job test
		with self.assertRaises(KeyError):
			client.wait_for_job("j-unknown")


class TestMockWorkerClient(unittest.TestCase):
	"""Verify MockWorkerClient handshake, connectivity, and health probing."""

	def test_worker_client_lifecycle(self) -> None:
		worker = MockWorkerClient(worker_pid=8888)
		self.assertFalse(worker.is_connected())

		resp = worker.connect()
		self.assertTrue(resp.accepted)
		self.assertEqual(resp.worker_pid, 8888)
		self.assertTrue(worker.is_connected())

		job_client = worker.get_job_client()
		self.assertIsInstance(job_client, MockJobClient)
		job_client.submit_job(JobSpec(job_id="job_in_worker", job_type="test"))

		health = worker.poll_health()
		self.assertTrue(health.is_healthy)
		self.assertEqual(health.worker_pid, 8888)
		self.assertEqual(health.active_jobs_count, 1)

		worker.disconnect()
		self.assertFalse(worker.is_connected())


if __name__ == "__main__":
	unittest.main()
