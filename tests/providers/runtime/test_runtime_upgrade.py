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
