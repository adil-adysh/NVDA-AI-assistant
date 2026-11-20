import hashlib
import json

import pytest

from tests.support import load_addon_module

module = load_addon_module("core.runtime_upgrade", namespace="runtime_upgrade_tests")


def package(root, version):
	path = root / version
	path.mkdir()
	(path / "python.exe").write_bytes(b"runtime")
	(path / "manifest.json").write_text(json.dumps({
		"runtime": "litert-lm", "version": version, "platform": "windows-x64",
		"files": {"python.exe": hashlib.sha256(b"runtime").hexdigest()},
	}))
	return path


def test_verified_upgrade_retires_old_package_only(tmp_path):
	new = package(tmp_path, "0.18.0")
	old = package(tmp_path, "0.15.0")
	models = tmp_path / "models"
	models.mkdir()
	assert module.finalize_litert_upgrade(new, "0.18.0") == []
	assert not old.exists()
	assert new.exists() and models.exists()


def test_corrupt_replacement_preserves_old(tmp_path):
	new = package(tmp_path, "0.18.0")
	old = package(tmp_path, "0.15.0")
	(new / "python.exe").write_bytes(b"corrupt")
	with pytest.raises(ValueError, match="checksum"):
		module.finalize_litert_upgrade(new, "0.18.0")
	assert old.exists()


def test_busy_cleanup_is_retried(tmp_path):
	new = package(tmp_path, "0.18.0")
	old = package(tmp_path, "0.15.0")
	assert module.finalize_litert_upgrade(new, "0.18.0", busy=True) == ["0.15.0"]
	assert old.exists()
	assert module.finalize_litert_upgrade(new, "0.18.0") == []
	assert not old.exists()


def test_previous_managed_runtime_is_detected(tmp_path):
	old = package(tmp_path, "0.18.0")
	assert module.has_previous_litert_runtime(tmp_path, "0.19.1")
	assert not module.has_previous_litert_runtime(tmp_path, "0.18.0")
	old_manifest = json.loads((old / "manifest.json").read_text())
	old_manifest["runtime"] = "custom"
	(old / "manifest.json").write_text(json.dumps(old_manifest))
	assert not module.has_previous_litert_runtime(tmp_path, "0.19.1")


def test_locked_cleanup_is_deferred(tmp_path, monkeypatch):
	new = package(tmp_path, "0.18.0")
	old = package(tmp_path, "0.15.0")
	def locked(path):
		raise PermissionError("busy")
	monkeypatch.setattr(module.shutil, "rmtree", locked)
	assert module.finalize_litert_upgrade(new, "0.18.0") == ["0.15.0"]
	assert old.exists()


def test_manifest_path_escape_preserves_old(tmp_path):
	new = package(tmp_path, "0.18.0")
	old = package(tmp_path, "0.15.0")
	manifest = json.loads((new / "manifest.json").read_text())
	manifest["files"]["../outside"] = "bad"
	(new / "manifest.json").write_text(json.dumps(manifest))
	with pytest.raises(ValueError, match="escapes"):
		module.finalize_litert_upgrade(new, "0.18.0")
	assert old.exists()


def test_cached_install_still_finalizes_upgrade(tmp_path, monkeypatch):
	server = load_addon_module("providers.runtime.server", namespace="cached_upgrade_tests")
	new = package(tmp_path, "0.18.0")
	instance = server.LiteRTServerSupervisor.__new__(server.LiteRTServerSupervisor)
	monkeypatch.setattr(instance, "_server_dir", lambda: new)
	monkeypatch.setattr(instance, "_server_python", lambda: new / "python.exe")
	calls = []
	monkeypatch.setattr(instance, "_finalize_upgrade", lambda path, progress: calls.append(path))
	assert instance.install() == new
	assert calls == [new]


def test_upgrade_stops_owned_server_before_cleanup(tmp_path, monkeypatch):
	server = load_addon_module("providers.runtime.server", namespace="stop_before_upgrade_tests")
	instance = server.LiteRTServerSupervisor.__new__(server.LiteRTServerSupervisor)
	instance._version = "0.19.1"
	monkeypatch.setattr(instance, "_has_previous_runtime", lambda: True)
	monkeypatch.setattr(instance, "_report", lambda *_args: None)
	calls = []

	class Client:
		def send_command(self, command, timeout):
			calls.append(command["command"])
			if command["command"] == "litert_stop":
				return {"success": True, "status": {"is_running": False, "is_adopted": False}}
			return {"success": True, "pending": []}

	monkeypatch.setattr(instance, "_get_worker_client", lambda **_kwargs: Client())
	instance._finalize_upgrade(tmp_path)
	assert calls == ["litert_stop", "litert_finalize_upgrade"]


def test_upgrade_preserves_old_runtime_if_owned_server_wont_stop(monkeypatch, tmp_path):
	server = load_addon_module("providers.runtime.server", namespace="failed_stop_upgrade_tests")
	instance = server.LiteRTServerSupervisor.__new__(server.LiteRTServerSupervisor)
	instance._version = "0.19.1"
	monkeypatch.setattr(instance, "_has_previous_runtime", lambda: True)
	monkeypatch.setattr(instance, "_report", lambda *_args: None)
	calls = []

	class Client:
		def send_command(self, command, timeout):
			calls.append(command["command"])
			return {"success": True, "status": {"is_running": True, "is_adopted": False}}

	monkeypatch.setattr(instance, "_get_worker_client", lambda **_kwargs: Client())
	with pytest.raises(server.LiteRTServerError, match="still running"):
		instance._finalize_upgrade(tmp_path)
	assert calls == ["litert_stop"]


def test_upgrade_leaves_adopted_server_running_and_defers_cleanup(monkeypatch, tmp_path):
	server = load_addon_module("providers.runtime.server", namespace="adopted_upgrade_tests")
	instance = server.LiteRTServerSupervisor.__new__(server.LiteRTServerSupervisor)
	instance._version = "0.19.1"
	monkeypatch.setattr(instance, "_has_previous_runtime", lambda: True)
	monkeypatch.setattr(instance, "_report", lambda *_args: None)
	calls = []

	class Client:
		def send_command(self, command, timeout):
			calls.append(command["command"])
			if command["command"] == "litert_stop":
				return {"success": True, "status": {"is_running": True, "is_adopted": True}}
			return {"success": True, "pending": ["0.18.0"]}

	monkeypatch.setattr(instance, "_get_worker_client", lambda **_kwargs: Client())
	instance._finalize_upgrade(tmp_path)
	assert calls == ["litert_stop", "litert_finalize_upgrade"]
