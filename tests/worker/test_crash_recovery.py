# -*- coding: utf-8 -*-
"""Unit tests for Worker Crash Resilience, Failure Isolation, and Circuit Breaker (Invariants A19, A20)."""

from __future__ import annotations

import time
import unittest
import uuid

from tests.support import load_addon_module

dto_mod = load_addon_module("core.job.dto")
sup_mod = load_addon_module("plugin.worker_supervisor")
worker_client_mod = load_addon_module("service.worker_client")

JobSpec = dto_mod.JobSpec
NamedPipeWorkerClient = worker_client_mod.NamedPipeWorkerClient
SupervisorState = sup_mod.SupervisorState
WorkerSupervisor = sup_mod.WorkerSupervisor


class TestCrashRecoveryAndCircuitBreaker(unittest.TestCase):
	"""Verify crash recovery, circuit breaker tripping, and NVDA failure isolation."""

	def _make_pipe_name(self, suffix: str) -> str:
		return f"\\\\.\\pipe\\test_crash_{suffix}_{uuid.uuid4().hex[:8]}"

	def test_kill_worker_while_idle(self) -> None:
		"""Verify supervisor catches idle worker kill and triggers recovery without freeze."""
		cmd_pipe = self._make_pipe_name("cmd")
		evt_pipe = self._make_pipe_name("evt")

		supervisor = WorkerSupervisor(
			cmd_pipe_name=cmd_pipe,
			evt_pipe_name=evt_pipe,
			ping_interval_seconds=0.05,
			liveness_timeout_seconds=0.15,
			auto_restart=True,
			base_backoff_seconds=0.05,
		)

		self.assertTrue(supervisor.start(auto_connect_pipes=True))
		initial_gen = supervisor.active_generation
		self.assertEqual(supervisor.state, SupervisorState.RUNNING)

		# Kill worker process while idle
		t0 = time.perf_counter()
		if supervisor._process:
			supervisor._process.kill()

		# Main thread remains responsive; supervisor detects crash and restarts
		deadline = time.monotonic() + 3.0
		while (
			time.monotonic() < deadline
			and supervisor.active_generation == initial_gen
		):
			time.sleep(0.05)
		while (
			time.monotonic() < deadline
			and supervisor.state != SupervisorState.RUNNING
		):
			time.sleep(0.05)

		t_elapsed = time.perf_counter() - t0
		self.assertLess(
			t_elapsed,
			3.0,
			"Crash detection and restart took longer than expected",
		)
		self.assertEqual(supervisor.state, SupervisorState.RUNNING)
		self.assertGreater(supervisor.active_generation, initial_gen)

		supervisor.stop()

	def test_kill_worker_during_active_job(self) -> None:
		"""Verify killing worker during active job does not hang caller and fails gracefully."""
		cmd_pipe = self._make_pipe_name("cmd")
		evt_pipe = self._make_pipe_name("evt")

		supervisor = WorkerSupervisor(
			cmd_pipe_name=cmd_pipe,
			evt_pipe_name=evt_pipe,
			auto_restart=False,
		)
		self.assertTrue(supervisor.start(auto_connect_pipes=False))

		client = NamedPipeWorkerClient(
			cmd_pipe_name=cmd_pipe,
			evt_pipe_name=evt_pipe,
		)
		client.connect()
		job_client = client.get_job_client()

		# Submit long-running compute job (50 steps)
		spec = JobSpec(
			job_id="crash-job-001",
			job_type="trivial_compute",
			payload={"steps": 50, "step_delay": 0.05},
		)
		job_id = job_client.submit_job(spec)
		self.assertEqual(job_id, "crash-job-001")

		# Kill worker mid-execution
		time.sleep(0.1)
		t0 = time.perf_counter()
		if supervisor._process:
			supervisor._process.kill()

		# Calling wait_for_job with short timeout should unblock or raise TimeoutError / error cleanly
		with self.assertRaises((TimeoutError, Exception)):
			job_client.wait_for_job(job_id, timeout_seconds=0.5)

		elapsed_ms = (time.perf_counter() - t0) * 1000.0
		# Confirm caller thread never hung indefinitely (< 1000ms SLA)
		self.assertLess(elapsed_ms, 1000.0)

		client.disconnect()
		supervisor.stop()

	def test_circuit_breaker_trips_after_3_crashes(self) -> None:
		"""Verify circuit breaker trips to FAILED_TRIPPED after >=3 crashes in 60s window."""
		cmd_pipe = self._make_pipe_name("cmd")
		evt_pipe = self._make_pipe_name("evt")

		notifications: list[str] = []

		def on_trip(message: str) -> None:
			notifications.append(message)

		supervisor = WorkerSupervisor(
			cmd_pipe_name=cmd_pipe,
			evt_pipe_name=evt_pipe,
			crash_window_seconds=60.0,
			max_crashes_in_window=3,
			auto_restart=False,
			on_circuit_breaker_tripped=on_trip,
		)

		self.assertTrue(supervisor.start(auto_connect_pipes=True))

		# Induce 3 consecutive crashes
		for crash_idx in range(1, 4):
			supervisor._handle_crash(reason=f"SIMULATED_CRASH_{crash_idx}")

		# Circuit breaker must be TRIPPED
		self.assertEqual(supervisor.state, SupervisorState.FAILED_TRIPPED)
		self.assertEqual(len(notifications), 1)
		self.assertIn("stopped responding", notifications[0])

		# Further start attempts must be blocked
		started_blocked = supervisor.start()
		self.assertFalse(started_blocked)
		self.assertEqual(supervisor.state, SupervisorState.FAILED_TRIPPED)

		# Reset circuit breaker allows recovery
		supervisor.reset_circuit_breaker()
		self.assertEqual(supervisor.state, SupervisorState.STOPPED)

		supervisor.stop()


if __name__ == "__main__":
	unittest.main()
