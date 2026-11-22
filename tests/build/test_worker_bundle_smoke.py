"""Exercise the shipped interpreter and native control jobs without installed NVDA."""
import os
import shutil
import threading
import time
import uuid

import pytest

from tests.support import ADDON_ROOT, load_addon_module


def test_isolated_packaged_worker_round_trips_catalog_fence(tmp_path, monkeypatch):
	bundle = ADDON_ROOT / "worker_host"
	if not (bundle / "python.exe").is_file():
		if os.environ.get("NVDA_AI_REQUIRE_PACKAGED_TESTS") == "1":
			pytest.fail("Build the private worker before running packaged smoke tests")
		pytest.skip("Private worker is not built")
	isolated = tmp_path / "isolated"
	for name in ("worker_host", "worker", "core"):
		shutil.copytree(ADDON_ROOT / name, isolated / name,
			ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
	for name in ("PYTHONPATH", "PYTHONHOME"):
		monkeypatch.delenv(name, raising=False)
	monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
	module = load_addon_module("plugin.worker_supervisor", namespace="packaged_fence_smoke")
	identity = uuid.uuid4().hex
	owner = module.WorkerSupervisor(
		worker_script_path=isolated / "worker" / "__main__.py",
		cmd_pipe_name=rf"\\.\pipe\packaged_fence_cmd_{identity}",
		evt_pipe_name=rf"\\.\pipe\packaged_fence_evt_{identity}",
		auto_restart=False,
	)
	owner.worker_python_path = isolated / "worker_host" / "python.exe"
	try:
		assert owner.start(), owner.stderr_buffer.get_text()
		client = owner.get_worker_client()
		assert client is not None
		status = client.send_command({"type": "llama_get_status"}, timeout=5)
		assert status.get("success"), status
		assert not status["status"]["is_running"]
		paused = client.send_command({"type": "llama_pause_startup"}, timeout=5)
		assert paused.get("success"), paused
		assert isinstance(paused.get("token"), int)
		# Health/control remain available while launch admission is fenced.
		health = client.send_command({"type": "worker_health_ping"}, timeout=5)
		assert health["type"] == "worker_health"
		deadline = time.monotonic() + 5
		while health["uptime_seconds"] < 1.1:
			assert time.monotonic() < deadline, health
			threading.Event().wait(0.1)
			health = client.send_command({"type": "worker_health_ping"}, timeout=5)
			assert health["type"] == "worker_health"
		resumed = client.send_command({"type": "llama_resume_startup", "token": paused["token"]}, timeout=5)
		assert resumed.get("success"), resumed
		stale = client.send_command({"type": "llama_resume_startup", "token": paused["token"]}, timeout=5)
		assert not stale.get("success"), stale
	finally:
		owner.stop()
