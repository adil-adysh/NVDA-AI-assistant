"""Runtime installation must retain the previous bundle on failure or cancellation."""

import json
import hashlib
import shutil
import zipfile

import pytest

from tests.support import load_addon_module

cancel = load_addon_module("core.job.cancellation", namespace="unpack_transaction_tests")
download = load_addon_module("worker.executors.download", namespace="unpack_transaction_tests")
unpack = load_addon_module("worker.executors.unpack", namespace="unpack_transaction_tests")


def make_archive(tmp_path, manifest=None):
	archive = tmp_path / "runtime.zip"
	with zipfile.ZipFile(archive, "w") as bundle:
		bundle.writestr("server.exe", b"new runtime")
		if manifest is not None:
			bundle.writestr("manifest.json", manifest)
	return archive


def test_cancellation_before_install_keeps_previous_runtime(tmp_path):
	archive = make_archive(tmp_path)
	target = tmp_path / "runtime"
	target.mkdir()
	(target / "server.exe").write_bytes(b"previous runtime")
	token = cancel.CancellationToken("cancel-install")

	def on_progress(message, percent):
		if percent == 90:
			token.cancel()

	with pytest.raises(download.OperationCancelledError):
		unpack.unpack_zip(archive, target, cancel_token=token, on_progress=on_progress)
	assert (target / "server.exe").read_bytes() == b"previous runtime"


def test_invalid_manifest_is_rejected_before_install(tmp_path):
	archive = make_archive(tmp_path, "{broken json")
	with pytest.raises(unpack.UnpackError):
		unpack.unpack_zip(archive, tmp_path / "runtime")
	assert not (tmp_path / "runtime").exists()


def test_manifest_cannot_verify_files_outside_bundle(tmp_path):
	outside = tmp_path / "outside.bin"
	outside.write_bytes(b"outside bundle")
	archive = make_archive(tmp_path, json.dumps({
		"files": {str(outside): hashlib.sha256(b"outside bundle").hexdigest()},
	}))
	with pytest.raises(unpack.UnpackError, match="path"):
		unpack.unpack_zip(archive, tmp_path / "runtime")


def test_failed_install_preserves_previous_runtime(tmp_path, monkeypatch):
	archive = make_archive(tmp_path)
	target = tmp_path / "runtime"
	target.mkdir()
	(target / "server.exe").write_bytes(b"previous runtime")
	original_copytree = shutil.copytree
	original_replace = unpack.os.replace

	def fail_copy(source, destination, *args, **kwargs):
		if str(destination) == str(target):
			raise OSError("disk failure")
		return original_copytree(source, destination, *args, **kwargs)

	def fail_replace(source, destination, *args, **kwargs):
		if str(destination) == str(target) and "extracted" in str(source):
			raise OSError("disk failure")
		return original_replace(source, destination, *args, **kwargs)

	monkeypatch.setattr(shutil, "copytree", fail_copy)
	monkeypatch.setattr(unpack.os, "replace", fail_replace)
	with pytest.raises(OSError, match="disk failure"):
		unpack.unpack_zip(archive, target)
	assert (target / "server.exe").read_bytes() == b"previous runtime"


def test_failed_rollback_retains_previous_runtime_backup(tmp_path, monkeypatch):
	archive = make_archive(tmp_path)
	target = tmp_path / "runtime"
	target.mkdir()
	(target / "server.exe").write_bytes(b"previous runtime")
	original_replace = unpack.os.replace

	def fail_replace(source, destination, *args, **kwargs):
		if str(destination) == str(target):
			raise OSError("destination unavailable")
		return original_replace(source, destination, *args, **kwargs)

	monkeypatch.setattr(unpack.os, "replace", fail_replace)
	with pytest.raises(OSError, match="destination unavailable"):
		unpack.unpack_zip(archive, target)
	retained_files = list(tmp_path.rglob("server.exe"))
	assert any(path.read_bytes() == b"previous runtime" for path in retained_files)
