"""The private runtime must preserve the no-test/no-bytecode package boundary."""

import zipfile

import pytest

from tests.support import PROJECT_ROOT, load_module


def builder():
	return load_module("worker_bundle_tests", PROJECT_ROOT / "scripts" / "build_worker_bundle.py")


def test_source_stdlib_excludes_tooling_and_bytecode(tmp_path):
	module = builder()
	source = tmp_path / "Lib"
	for name in ("encodings/__init__.py", "json/__init__.py", "test/test_json.py", "site-packages/foo.py", "__pycache__/foo.pyc", "json/tests/fixture.py"):
		path = source / name
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text("pass\n")
	destination = tmp_path / "python313.zip"
	module.build_stdlib_archive(source, destination)
	with zipfile.ZipFile(destination) as archive:
		assert set(archive.namelist()) == {"encodings/__init__.py", "json/__init__.py"}


def test_bundle_rejects_nested_bytecode(tmp_path):
	module = builder()
	with zipfile.ZipFile(tmp_path / "python313.zip", "w") as archive:
		archive.writestr("encodings/__init__.pyc", b"bytecode")
	with pytest.raises(ValueError, match="forbidden"):
		module.validate_bundle(tmp_path)


def test_incomplete_bundle_cannot_be_reused(tmp_path):
	module = builder()
	with pytest.raises(ValueError, match="missing"):
		module.validate_bundle(tmp_path)
