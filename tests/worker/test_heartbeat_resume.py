"""Exercise the real watchdog after scheduler pauses and stale responses."""

from unittest.mock import Mock

import pytest

from tests.support import load_addon_module

supervisor_module = load_addon_module("plugin.worker_supervisor", namespace="heartbeat_resume_tests")


@pytest.mark.parametrize("response_generation, response_type, healthy", [
	(5, "worker_health", True),
	(4, "worker_health", False),
	(6, "worker_health", False),
	(5, "unrelated_response", False),
])
def test_watchdog_probes_after_pause(monkeypatch, response_generation, response_type, healthy):
	supervisor = supervisor_module.WorkerSupervisor(auto_restart=False)
	supervisor.state = supervisor_module.SupervisorState.RUNNING
	supervisor.active_generation = 5
	supervisor._last_pong_monotonic = 10.0
	monkeypatch.setattr(supervisor_module.time, "monotonic", lambda: 3000.0)
	monkeypatch.setattr(supervisor_module.time, "sleep", lambda _: None)
	pipe = Mock(is_connected=True)
	response = {
		"type": response_type, "generation": response_generation,
		"worker_pid": 123, "uptime_seconds": 3000.0,
		"active_jobs_count": 0, "active_sessions_count": 0,
		"cpu_percent": 0.0, "rss_memory_bytes": 0, "is_healthy": True,
	}
	def read_frame(**kwargs):
		supervisor._shutdown_event.set()
		return response
	pipe.read_frame.side_effect = read_frame
	supervisor._cmd_client = pipe
	supervisor._handle_crash = Mock()
	supervisor._run_heartbeat_loop()
	pipe.write_frame.assert_called_once()
	if healthy:
		supervisor._handle_crash.assert_not_called()
		assert supervisor.latest_health.generation == 5
		assert supervisor._last_pong_monotonic == 3000.0
	else:
		assert supervisor.latest_health is None
		assert supervisor._last_pong_monotonic == 10.0
		supervisor._handle_crash.assert_called_once()
