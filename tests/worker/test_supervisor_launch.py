"""Launch and recovery regressions that in-process worker tests cannot cover."""

import time
import uuid
import pytest

from tests.support import PROJECT_ROOT, load_addon_module

supervisor_module = load_addon_module("plugin.worker_supervisor", namespace="supervisor_launch_tests")


def test_first_worker_crash_queues_feedback_once(monkeypatch):
	import sys
	import types
	ui = types.ModuleType("supervisor_launch_tests.ui.nvda_ui")
	ui.message = lambda text: None
	queued = []
	ui.queue = lambda *args: queued.append(args)
	monkeypatch.setitem(sys.modules, ui.__name__, ui)
	supervisor = supervisor_module.WorkerSupervisor(auto_restart=False)
	supervisor.state = supervisor_module.SupervisorState.RUNNING
	monkeypatch.setattr(supervisor, "_teardown_process_handles", lambda **kwargs: None)
	supervisor._handle_crash("PIPE_BROKEN")
	supervisor._handle_crash("PIPE_BROKEN")
	assert len(queued) == 1
	assert "worker" in queued[0][1]


def test_default_entrypoint_is_independent_of_working_directory(tmp_path, monkeypatch):
	monkeypatch.chdir(tmp_path)
	supervisor = supervisor_module.WorkerSupervisor(auto_restart=False)
	bundle = PROJECT_ROOT / "addon/globalPlugins/AI-assistant/worker_host"
	expected = bundle / "ai_assistant_worker.py" if (bundle / "python.exe").exists() else PROJECT_ROOT / "ai_assistant_worker.py"
	assert supervisor.worker_script_path == expected
	assert supervisor.worker_script_path.is_file()


def test_nvda_executable_is_never_used_as_python(monkeypatch):
	monkeypatch.setattr(supervisor_module.sys, "executable", "C:/NVDA/nvda.exe")
	supervisor = supervisor_module.WorkerSupervisor(worker_script_path=PROJECT_ROOT / "ai_assistant_worker.py", auto_restart=False)
	with pytest.raises(RuntimeError, match="NVDA"):
		supervisor._spawn_worker_process()


def test_restarted_worker_reports_current_generation():
	token = uuid.uuid4().hex
	supervisor = supervisor_module.WorkerSupervisor(
		cmd_pipe_name=rf"\\.\pipe\generation_cmd_{token}",
		evt_pipe_name=rf"\\.\pipe\generation_evt_{token}",
		worker_script_path=PROJECT_ROOT / "ai_assistant_worker.py",
		ping_interval_seconds=0.05,
		liveness_timeout_seconds=0.5,
		auto_restart=False,
	)
	supervisor.active_generation = 2
	try:
		assert supervisor.start()
		deadline = time.monotonic() + 2
		while supervisor.latest_health is None and time.monotonic() < deadline:
			time.sleep(0.01)
		assert supervisor.latest_health is not None
		assert supervisor.latest_health.generation == 2
		assert supervisor.is_running
	finally:
		supervisor.stop()
