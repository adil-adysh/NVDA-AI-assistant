"""Standalone packaged worker IPC, native imports, and download execution."""

import hashlib
import os
import shutil
import subprocess
import time
import uuid
import zipfile
import struct
from types import SimpleNamespace

import pytest

from tests.support import ADDON_ROOT, PROJECT_ROOT, load_addon_module
from tests.support.llama_flow import RuntimeSurface

supervisors = load_addon_module("plugin.worker_supervisor", namespace="packaged_worker_smoke")
downloads = load_addon_module("providers.runtime.download_client", namespace="packaged_worker_smoke")


def require_artifact(message):
	if os.getenv('NVDA_AI_REQUIRE_PACKAGED_TESTS') == '1':
		pytest.fail(message)
	pytest.skip(message)


@pytest.mark.parametrize("artifact", ["bundle", "nvda-addon"])
def test_packaged_worker_runs_outside_checkout(tmp_path, monkeypatch, artifact):
	llama_executable = shutil.which("llama-server")
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
		for name in ("worker_host", "worker", "core", "service", "config", "lib"):
			shutil.copytree(ADDON_ROOT / name, addon / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
	monkeypatch.chdir(tmp_path)
	monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
	monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
	monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
	for variable in ("LLAMA_CACHE", "HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
		monkeypatch.delenv(variable, raising=False)
	monkeypatch.setenv("PATH", "")
	monkeypatch.setenv("PYTHONPATH", str(tmp_path / "invalid-python-path"))
	python = addon / "worker_host" / "python.exe"
	probe = subprocess.run([str(python), "-B", "-c", "import win32file, runtime_supervisor, embedding_engine, memory_engine; assert runtime_supervisor.RuntimeSupervisor('llama-server', '127.0.0.1', 9380).status().state == 'stopped'"], capture_output=True, timeout=10)
	assert probe.returncode == 0, probe.stderr.decode(errors="replace")
	token = uuid.uuid4().hex
	supervisor = supervisors.WorkerSupervisor(
		worker_script_path=addon / "worker" / "__main__.py",
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
		assert "job.runtime_command" in client._handshake_response.negotiated_capabilities
		asset_root = tmp_path / "asset-cache"
		asset_root.mkdir()
		asset_path = asset_root / "cached.gguf"
		asset_bytes = b"GGUF" + struct.pack("<IQQ", 3, 0, 0) + bytes(32)
		asset_path.write_bytes(asset_bytes)
		discovered = client.send_command({"type": "llama_discover_assets", "command": "llama_discover_assets",
			"roots": [{"path": str(asset_root), "source": "user_folder"}], "generation": 7}, timeout=10)
		assert discovered.get("success"), discovered
		snapshot = discovered["result"]
		assert snapshot["generation"] == 7 and len(snapshot["assets"]) == 1 and not snapshot["errors"]
		manager_module = load_addon_module("providers.llama_manager", namespace="packaged_worker_smoke")
		runtime = RuntimeSurface()
		manager = manager_module.LlamaCppModelManager(config=SimpleNamespace(model_name="", num_ctx=8192), cache_dir=tmp_path / "managed-configurations",
			worker_client=client, supervisor=runtime)
		manager.create_configuration_from_asset(snapshot["assets"][0]["token"], "cached-model", "Cached model", {})
		assert manager._catalog.find_exact("cached-model").display_name == "Cached model"
		assert asset_path.read_bytes() == asset_bytes
		manager.set_active_model("cached-model")
		assert manager.active_model_id == "cached-model"
		manager.set_runtime_options("cached-model", {"ctx-size": "4096", "cache-type-k": "q8_0"})
		manager.create_configuration("owner/model:Q4_K_M", "remote", "Remote")
		preset_source = tmp_path / "import-preset.ini"
		preset_source.write_text("version = 1\n[imported]\nhf-repo = owner/imported\n", encoding="utf-8")
		preview = manager.preview_preset_import(str(preset_source))
		manager.commit_preset_import(preview, replace_ids=())
		assert manager.get_available_model_ids() == ["cached-model", "imported", "remote"]
		manager.delete_model("imported")
		assert manager.get_available_model_ids() == ["cached-model", "remote"]
		before = (tmp_path / "managed-configurations/models.json").read_bytes()
		asset_path.write_bytes(b"changed asset")
		with pytest.raises(Exception, match="changed|missing"):
			manager.create_configuration_from_asset(snapshot["assets"][0]["token"], "changed", "Changed", {})
		assert (tmp_path / "managed-configurations/models.json").read_bytes() == before
		assert not runtime.starts
		assert client.send_command({"type": "llama_get_status"}, timeout=5)["status"]["state"] == "stopped"
		projector_path = asset_root / "mmproj.gguf"
		projector_path.write_bytes(asset_bytes)
		companions = client.send_command({"type": "llama_resolve_companions", "command": "llama_resolve_companions",
			"companions": [{"role": "vision", "source": str(projector_path), "kind": "local_file"}]}, timeout=10)
		assert companions.get("success"), companions
		assert companions["result"]["companions"][0]["local_path"] == str(projector_path)
		unload = client.send_command({"type": "llama_unload_model", "command": "llama_unload_model", "model_id": "cached-model", "timeout_seconds": 1}, timeout=5)
		assert not unload.get("success"), unload
		assert projector_path.read_bytes() == asset_bytes
		if llama_executable:
			inspected = client.send_command({"type": "llama_inspect_options", "command": "llama_inspect_options",
				"executable": llama_executable}, timeout=10)
			assert inspected.get("success") and "cache-type-k" in inspected.get("options", []), inspected
		preset = tmp_path / "runtime-models.ini"
		preset.write_text("version = 1\n[stale]\nhf-repo = owner/stale\n", encoding="utf-8")
		configured = client.send_command({"type": "llama_configure_preset", "command": "llama_configure_preset",
			"preset_path": str(preset), "models": [{"model_id": "snapshot", "kind": "hugging_face",
			"source": "owner/model", "preset_options": {"cache-type-k": "q8_0", "n-cpu-moe": "4"}}]}, timeout=10)
		assert configured.get("success"), configured
		assert "stale" not in preset.read_text(encoding="utf-8")
		assert "n-cpu-moe = 4" in preset.read_text(encoding="utf-8")
		cache_root = tmp_path / "appdata/nvda/AIAssistant/models/llama-cpp/cache"
		cache_root.mkdir(parents=True)
		cached_model = cache_root / "smoke.gguf"
		cached_model.write_bytes(b"owned cache fixture")
		import json
		(cache_root.parent / "models.json").write_text(json.dumps({"version": 1, "models": [{"model_id": "smoke", "ownership": "addon", "cached_path": str(cached_model)}]}), encoding="utf-8")
		deleted = client.send_command({"type": "llama_delete_cache", "command": "llama_delete_cache",
			"cache_root": str(cache_root), "path": str(cached_model), "model_id": "smoke"}, timeout=10)
		assert deleted.get("success") and not cached_model.exists(), deleted
		catalog = client.run_job("embedding", {"operation": "list"}, timeout=10)
		assert catalog.get("success") and catalog.get("models"), catalog
		invalid = client.run_job("embedding", {"operation": "embed",
			"model_id": catalog["models"][0]["id"], "texts": [" "]}, timeout=10)
		assert invalid.get("success") is False and "empty" in invalid.get("error_message", ""), invalid
		for operation in ("save", "load", "list", "delete"):
			stored = client.run_job("conversation", {"operation": operation, "conversation_id": "smoke",
				"messages": [{"role": "user", "parts": [{"type": "text", "text": "Saved message"}]}]}, timeout=10)
			assert stored.get("success"), stored
			if operation == "load":
				assert stored["messages"][0]["parts"][0]["text"] == "Saved message"

		assert (tmp_path / "appdata/nvda/AIAssistant/conversations.db").is_file()
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
