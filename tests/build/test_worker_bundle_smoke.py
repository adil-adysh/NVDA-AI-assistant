"""Standalone packaged worker IPC, native imports, and download execution."""

import hashlib
import os
import shutil
import subprocess
import time
import uuid
import zipfile

import pytest

from tests.support import ADDON_ROOT, PROJECT_ROOT, load_addon_module

supervisors = load_addon_module("plugin.worker_supervisor", namespace="packaged_worker_smoke")
downloads = load_addon_module("providers.runtime.download_client", namespace="packaged_worker_smoke")


def require_artifact(message):
	if os.getenv('NVDA_AI_REQUIRE_PACKAGED_TESTS') == '1':
		pytest.fail(message)
	pytest.skip(message)


@pytest.mark.parametrize("artifact", ["bundle", "nvda-addon"])
def test_packaged_worker_runs_outside_checkout(tmp_path, monkeypatch, artifact):
	source = ADDON_ROOT / "worker_host"
	if not (source / "python.exe").is_file():
		require_artifact("Build private worker with uv run python scripts/build_worker_bundle.py")
	addon = tmp_path / "isolated-addon"
	if artifact == "nvda-addon":
		packages = sorted(PROJECT_ROOT.glob("AIAssistant-*.nvda-addon"), key=lambda path: path.stat().st_mtime)
		if not packages:
			require_artifact("Build .nvda-addon with uv run scons")
		with zipfile.ZipFile(packages[-1]) as archive:
			archive.extractall(addon)
		addon = addon / "globalPlugins" / "AI-assistant"
	else:
		for name in ("worker_host", "worker", "core"):
			shutil.copytree(ADDON_ROOT / name, addon / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
	monkeypatch.chdir(tmp_path)
	monkeypatch.setenv("PATH", "")
	monkeypatch.setenv("PYTHONPATH", str(tmp_path / "invalid-python-path"))
	python = addon / "worker_host" / "python.exe"
	probe = subprocess.run([str(python), "-B", "-c", "import win32file, runtime_supervisor; assert runtime_supervisor.RuntimeSupervisor('llama-server', '127.0.0.1', 9380).status().state == 'stopped'"], capture_output=True, timeout=10)
	assert probe.returncode == 0, probe.stderr.decode(errors="replace")
	token = uuid.uuid4().hex
	supervisor = supervisors.WorkerSupervisor(
		worker_script_path=addon / "worker_host" / "ai_assistant_worker.py",
		cmd_pipe_name=rf"\\.\pipe\bundle_cmd_{token}",
		evt_pipe_name=rf"\\.\pipe\bundle_evt_{token}", auto_restart=False,
	)
	supervisor.worker_python_path = python
	supervisor.active_generation = 3
	try:
		assert supervisor.start(), supervisor.stderr_buffer.get_text()
		client = supervisor.get_worker_client()
		# Exercise the actual packaged watchdog for multiple 0.5-second ticks.
		# A fast handshake/download alone can finish before its first parent check.
		deadline = time.monotonic() + 10
		while True:
			health = client.send_command({'type': 'worker_health_ping'}, timeout=3)
			assert health.get('is_healthy'), health
			if health.get('uptime_seconds', 0) >= 1.5:
				break
			assert time.monotonic() < deadline, supervisor.stderr_buffer.get_text()
		response = client.send_command({"type": "llama_get_status", "command": "llama_get_status"}, timeout=5)
		assert response.get("status", {}).get("state") == "stopped", response
		payload = tmp_path / "input.bin"
		payload.write_bytes(b"packaged worker transfer")
		destination = tmp_path / "output.bin"
		result = downloads.WorkerDownloadClient(client).download_model(
			payload.as_uri(), destination,
			expected_sha256=hashlib.sha256(payload.read_bytes()).hexdigest(), timeout_seconds=5,
		)
		assert result == destination
		assert result.read_bytes() == payload.read_bytes()
	finally:
		supervisor.stop()
	assert supervisor.process_pid is None
