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
	assert old.with_name(".litert-lm-retired-0.15.0").exists()
	assert module.has_previous_litert_runtime(tmp_path, "0.18.0")


def test_partial_removal_can_be_retried(tmp_path, monkeypatch):
	new = package(tmp_path, "0.19.1")
	old = package(tmp_path, "0.18.0")

	def interrupted(path):
		(path / "manifest.json").unlink()
		raise PermissionError("busy")

	with monkeypatch.context() as patch:
		patch.setattr(module.shutil, "rmtree", interrupted)
		assert module.finalize_litert_upgrade(new, "0.19.1") == ["0.18.0"]
	assert module.has_previous_litert_runtime(tmp_path, "0.19.1")
	assert module.finalize_litert_upgrade(new, "0.19.1") == []
	assert not old.exists()
	assert not module.has_previous_litert_runtime(tmp_path, "0.19.1")


def test_unrecognized_platform_is_preserved(tmp_path):
	new = package(tmp_path, "0.19.1")
	old = package(tmp_path, "0.18.0")
	manifest = old / "manifest.json"
	data = json.loads(manifest.read_text())
	data["platform"] = "custom"
	manifest.write_text(json.dumps(data))
	assert module.finalize_litert_upgrade(new, "0.19.1") == []
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
	monkeypatch.setattr(instance, "_finalize_upgrade", lambda progress: calls.append(progress))
	assert instance.install() == new
	assert calls == [None]


def test_install_redownloads_invalid_cache_then_finalizes(tmp_path, monkeypatch):
	server = load_addon_module("providers.runtime.server", namespace="repair_upgrade_tests")
	version = server.DEFAULT_LITERT_VERSION
	new = package(tmp_path, version)
	instance = server.LiteRTServerSupervisor(version=version)
	monkeypatch.setattr(instance, "_server_dir", lambda: new)
	calls = []

	class Client:
		def send_command(self, command, timeout):
			calls.append(command["command"])
			if len(calls) == 1:
				return {"success": False, "error_code": "LITERT_PACKAGE_INVALID", "error_message": "checksum mismatch"}
			return {"success": True, "pending": []}

	def download(**kwargs):
		assert kwargs["recheck_cache"]
		calls.append("download")

	monkeypatch.setattr(instance, "_get_worker_client", lambda **_: Client())
	monkeypatch.setattr(instance._download_service, "download", download)
	assert instance.install() == new
	assert calls == ["litert_finalize_upgrade", "download", "litert_finalize_upgrade"]


def test_upgrade_removes_all_older_managed_releases(tmp_path):
	new = package(tmp_path, "0.19.1")
	old = [package(tmp_path, version) for version in ("0.15.0", "0.18.0", "0.19.0")]
	newer = package(tmp_path, "0.20.0")
	assert module.finalize_litert_upgrade(new, "0.19.1") == []
	assert all(not path.exists() for path in old)
	assert new.exists() and newer.exists()


def test_upgrade_removes_partial_install_backup(tmp_path):
	new = package(tmp_path, "0.19.1")
	backup = new.with_name(".0.19.1.backup-" + "a" * 32)
	new.rename(backup)
	(backup / "manifest.json").unlink()
	new = package(tmp_path, "0.19.1")
	assert module.has_previous_litert_runtime(tmp_path, "0.19.1")
	assert module.finalize_litert_upgrade(new, "0.19.1") == []
	assert new.exists() and not backup.exists()


def test_cancellation_after_verification_leaves_old_runtime(tmp_path):
	new = package(tmp_path, "0.19.1")
	old = package(tmp_path, "0.18.0")
	cancelled = False

	def prepare_cleanup(_paths):
		nonlocal cancelled
		cancelled = True
		return True

	def check_cancelled():
		if cancelled:
			raise InterruptedError

	with pytest.raises(InterruptedError):
		module.finalize_litert_upgrade(
			new, "0.19.1", prepare_cleanup=prepare_cleanup, check_cancelled=check_cancelled,
		)
	assert old.exists()


@pytest.mark.parametrize(("running", "expected_stop", "expected_pending"), [
	("old", True, []),
	("current", False, []),
	("adopted", False, ["0.18.0"]),
	("old_locked", True, ["0.18.0"]),
	("old_corrupt_replacement", False, None),
])
def test_worker_verifies_before_stopping_only_obsolete_owned_server(
	tmp_path, monkeypatch, running, expected_stop, expected_pending,
):
	worker = load_addon_module("worker.executors.litert", namespace="upgrade_worker_tests")
	old = package(tmp_path, "0.18.0")
	version = worker.DEFAULT_LITERT_VERSION
	new = package(tmp_path, version)
	monkeypatch.setattr(worker, "default_runtime_dir", lambda _: new)
	executor = worker.LiteRTWorkerExecutor.__new__(worker.LiteRTWorkerExecutor)
	status = {
		"is_running": True,
		"is_adopted": running == "adopted",
		"startup_identity": json.dumps({"python": str((new if running == "current" else old) / "python.exe")}),
	}
	monkeypatch.setattr(executor, "get_status", lambda: status)
	stops = []

	def stop(timeout_seconds):
		stops.append(timeout_seconds)
		return {"is_running": running == "old_locked"}

	monkeypatch.setattr(executor, "stop", stop)
	if expected_pending is None:
		(new / "python.exe").write_bytes(b"corrupt")
		with pytest.raises(ValueError, match="checksum"):
			executor.finalize_upgrade(version)
		assert old.exists()
	else:
		assert executor.finalize_upgrade(version) == expected_pending
	assert bool(stops) == expected_stop
