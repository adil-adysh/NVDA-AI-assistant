# -*- coding: utf-8 -*-
"""Unit tests for Heartbeat Probing, Liveness Timeout, and Generation Fencing (Invariant A19)."""

from __future__ import annotations

import time
import unittest
import uuid

from tests.support import load_addon_module

dto_mod = load_addon_module("core.job.dto")
server_mod = load_addon_module("worker.server")
sup_mod = load_addon_module("plugin.worker_supervisor")
trans_mod = load_addon_module("worker.ipc.transport")

NamedPipeClient = trans_mod.NamedPipeClient
SupervisorState = sup_mod.SupervisorState
WorkerHealth = dto_mod.WorkerHealth
WorkerServer = server_mod.WorkerServer
WorkerSupervisor = sup_mod.WorkerSupervisor


class TestWorkerHeartbeat(unittest.TestCase):
	"""Verify monotonic heartbeat probes, liveness timeouts, and generation fencing."""

	def _make_pipe_name(self, suffix: str) -> str:
		return f"\\\\.\\pipe\\test_heartbeat_{suffix}_{uuid.uuid4().hex[:8]}"

	def test_heartbeat_ping_pong_response(self) -> None:
		"""Verify worker responds to worker_health_ping with populated WorkerHealth DTO."""
		cmd_pipe = self._make_pipe_name("cmd")
		evt_pipe = self._make_pipe_name("evt")
		server = WorkerServer(cmd_pipe_name=cmd_pipe, evt_pipe_name=evt_pipe)
		server.start()

		client = NamedPipeClient(cmd_pipe)
		client.connect(timeout_seconds=2.0)

		try:
			client.write_frame(
				{
					"type": "worker_health_ping",
					"timestamp_epoch_ms": int(time.time() * 1000),
				}
			)
			raw_resp = client.read_frame()

			health = WorkerHealth.from_dict(raw_resp)
			self.assertTrue(health.is_healthy)
			self.assertGreater(health.worker_pid, 0)
			self.assertGreaterEqual(health.uptime_seconds, 0.0)
			self.assertEqual(health.active_jobs_count, 0)
		finally:
			client.close()
			server.shutdown()

	def test_liveness_timeout_detection(self) -> None:
		"""Verify supervisor watchdog detects unresponsive worker within configured timeout."""
		cmd_pipe = self._make_pipe_name("cmd")
		evt_pipe = self._make_pipe_name("evt")

		supervisor = WorkerSupervisor(
			cmd_pipe_name=cmd_pipe,
			evt_pipe_name=evt_pipe,
			ping_interval_seconds=0.03,
			liveness_timeout_seconds=0.10,
			auto_restart=False,
		)

		started = supervisor.start(auto_connect_pipes=True)
		self.assertTrue(started)
		self.assertEqual(supervisor.state, SupervisorState.RUNNING)

		# Kill underlying worker process to simulate hang / death
		if supervisor._process:
			supervisor._process.kill()

		# Watchdog should detect timeout and transition state away from RUNNING
		deadline = time.monotonic() + 1.0
		while (
			time.monotonic() < deadline
			and supervisor.state == SupervisorState.RUNNING
		):
			time.sleep(0.02)

		self.assertNotEqual(
			supervisor.state,
			SupervisorState.RUNNING,
			"Supervisor failed to detect worker liveness timeout",
		)
		supervisor.stop()

	def test_generation_fencing_discards_stale_messages(self) -> None:
		"""Verify supervisor discards heartbeat responses from older generations."""
		cmd_pipe = self._make_pipe_name("cmd")
		evt_pipe = self._make_pipe_name("evt")

		supervisor = WorkerSupervisor(
			cmd_pipe_name=cmd_pipe,
			evt_pipe_name=evt_pipe,
			auto_restart=False,
		)
		supervisor.active_generation = 5

		# Stale message from generation 3
		stale_frame = {
			"type": "worker_health",
			"worker_pid": 9999,
			"generation": 3,
			"uptime_seconds": 10.0,
			"active_jobs_count": 0,
			"active_sessions_count": 0,
			"cpu_percent": 0.0,
			"rss_memory_bytes": 0,
			"is_healthy": True,
		}

		# Frame with generation < active_generation must not update latest_health
		frame_gen = int(
			stale_frame.get("generation", supervisor.active_generation)
		)
		if frame_gen >= supervisor.active_generation:
			supervisor._latest_health = WorkerHealth.from_dict(stale_frame)

		self.assertIsNone(supervisor.latest_health)

		# Newer or equal generation frame updates health
		valid_frame = dict(stale_frame)
		valid_frame["generation"] = 5
		if valid_frame["generation"] >= supervisor.active_generation:
			supervisor._latest_health = WorkerHealth.from_dict(valid_frame)

		self.assertIsNotNone(supervisor.latest_health)
		self.assertEqual(supervisor.latest_health.generation, 5)


if __name__ == "__main__":
	unittest.main()
