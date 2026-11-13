"""Real runtime registry imports; tiny fixtures do not test model inference."""
import os
from pathlib import Path
import subprocess

import pytest

from tests.support import load_addon_module

executor = load_addon_module("worker.executors.litert", namespace="litert_runtime_smoke")


@pytest.fixture
def runtime_python():
	path = executor.default_python_exe()
	if not path.is_file():
		if os.getenv("NVDA_AI_REQUIRE_LITERT_TESTS") == "1":
			pytest.fail("Build and install the pinned LiteRT runtime before this test")
		pytest.skip("Pinned LiteRT runtime is not installed")
	return path


def test_real_runtime_imports_local_file_without_deleting_source(tmp_path, runtime_python):
	source = tmp_path / "model.litertlm"
	source.write_bytes(b"registry-import-fixture")
	worker = executor.LiteRTWorkerExecutor()
	result = worker.import_model(source, "local-test", python_exe=runtime_python, litert_dir=tmp_path / "registry")
	assert result["success"]
	assert Path(result["imported_path"]).read_bytes() == source.read_bytes()
	assert source.exists()


def test_real_huggingface_cli_imports_only_requested_artifact(tmp_path, runtime_python):
	source = tmp_path / "model.litertlm"
	source.write_bytes(b"registry-import-fixture")
	# Replace only the remote download boundary, using the real 0.18 CLI and registry.
	code = '''
import importlib, sys
from unittest.mock import patch
from click.testing import CliRunner
module = importlib.import_module("litert_lm_cli.commands.import")
with patch.object(module.huggingface_download, "download_from_huggingface", return_value=sys.argv[1]) as download:
    result = CliRunner().invoke(module.import_model, ["--from-huggingface-repo", "owner/model", "--huggingface-token", "smoke-test-token", "variants/model.litertlm", "hf-test"])
    assert result.exit_code == 0, result.output
    download.assert_called_once_with(repo_id="owner/model", filename="variants/model.litertlm", token="smoke-test-token")
'''
	env = dict(os.environ, LITERT_LM_DIR=str(tmp_path / "registry"))
	result = subprocess.run([str(runtime_python), "-B", "-c", code, str(source)], env=env, capture_output=True, text=True, timeout=30)
	assert result.returncode == 0, result.stderr
	assert (tmp_path / "registry/models/hf-test/model.litertlm").read_bytes() == source.read_bytes()


def test_packaged_worker_starts_and_stops_real_litert_server(tmp_path, runtime_python, monkeypatch):
	import socket
	import uuid
	import urllib.request
	from tests.support import ADDON_ROOT
	supervisors = load_addon_module("plugin.worker_supervisor", namespace="litert_runtime_smoke")
	private_python = ADDON_ROOT / "worker_host/python.exe"
	if not private_python.is_file():
		if os.getenv("NVDA_AI_REQUIRE_PACKAGED_TESTS") == "1":
			pytest.fail("Build the private worker first")
		pytest.skip("Private worker is not built")
	with socket.socket() as reservation:
		reservation.bind(("127.0.0.1", 0))
		port = reservation.getsockname()[1]
	key = uuid.uuid4().hex
	monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
	owner = supervisors.WorkerSupervisor(worker_script_path=ADDON_ROOT / "worker/__main__.py",
		cmd_pipe_name=rf"\\.\pipe\real_litert_cmd_{key}", evt_pipe_name=rf"\\.\pipe\real_litert_evt_{key}",
		auto_restart=False)
	owner.worker_python_path = private_python
	try:
		assert owner.start(), owner.stderr_buffer.get_text()
		client = owner.get_worker_client()
		ready = client.send_command({"type": "litert_ensure_ready", "python_exe": str(runtime_python),
			"litert_dir": str(tmp_path / "registry"), "host": "127.0.0.1", "port": port,
			"version": executor.DEFAULT_LITERT_VERSION, "timeout_seconds": 15}, timeout=20)
		assert ready.get("success") and ready.get("status", {}).get("is_ready"), ready
		with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=3) as response:
			assert response.status == 200
		stopped = client.send_command({"type": "litert_stop", "timeout_seconds": 3}, timeout=5)
		assert stopped.get("success") and not stopped.get("status", {}).get("is_running"), stopped
	finally:
		owner.stop()
