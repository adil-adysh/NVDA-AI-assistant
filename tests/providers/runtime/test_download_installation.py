"""The direct installer must preserve an existing runtime on filesystem errors."""

import pytest

from tests.support import load_addon_module

module = load_addon_module("providers.runtime.download", namespace="direct_installation_tests")


def test_failed_staging_preserves_existing_runtime(tmp_path, monkeypatch):
	source = tmp_path / "source"
	source.mkdir()
	(source / "server.exe").write_bytes(b"new runtime")
	target = tmp_path / "installed"
	target.mkdir()
	(target / "server.exe").write_bytes(b"previous runtime")

	def fail_copy(*args, **kwargs):
		raise OSError("disk full")

	monkeypatch.setattr(module.shutil, "copytree", fail_copy)
	with pytest.raises(OSError, match="disk full"):
		module.RuntimeDownloadService._atomic_move(source, target)
	assert (target / "server.exe").read_bytes() == b"previous runtime"
