"""Native packaging must use uv's pinned project environment."""

from types import SimpleNamespace

import pytest

from tests.support import PROJECT_ROOT, load_module


def builder(monkeypatch):
	monkeypatch.syspath_prepend(str(PROJECT_ROOT / "scripts"))
	return load_module("native_build_environment_tests", PROJECT_ROOT / "scripts" / "build.py")


def test_global_python_reexecutes_through_uv_and_preserves_build_options(monkeypatch):
	module = builder(monkeypatch)
	monkeypatch.setattr(module.sys, "prefix", str(PROJECT_ROOT / "global-python"))
	monkeypatch.setattr(module.sys, "argv", ["scripts/build.py", "--debug", "--install-only"])
	monkeypatch.delenv("NVDA_AI_BUILD_UV_CHILD", raising=False)
	monkeypatch.setattr(module.shutil, "which", lambda _name: "uv.exe")
	calls = []
	monkeypatch.setattr(module.subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs)) or SimpleNamespace(returncode=7))
	assert module.reexec_in_project_environment() == 7
	assert calls[0][0] == ["uv.exe", "run", "--locked", "--project", str(PROJECT_ROOT), "python", str(PROJECT_ROOT / "scripts" / "build.py"), "--debug", "--install-only"]
	assert calls[0][1]["env"]["NVDA_AI_BUILD_UV_CHILD"] == "1"


def test_pinned_project_python_does_not_reexecute(monkeypatch):
	module = builder(monkeypatch)
	monkeypatch.setattr(module.sys, "prefix", str(PROJECT_ROOT / ".venv"))
	assert module.reexec_in_project_environment() is None


def test_missing_uv_explains_how_to_repair_build_environment(monkeypatch):
	module = builder(monkeypatch)
	monkeypatch.setattr(module.shutil, "which", lambda _name: None)
	with pytest.raises(RuntimeError, match="uv sync --locked"):
		module.project_build_command()


def test_invalid_worker_environment_fails_before_any_compilation(monkeypatch, capsys):
	module = builder(monkeypatch)
	import build_worker_bundle
	monkeypatch.setattr(module, "reexec_in_project_environment", lambda: None)
	monkeypatch.setattr(module.sys, "argv", ["scripts/build.py"])
	def reject():
		raise RuntimeError("wrong pinned Python")
	monkeypatch.setattr(build_worker_bundle, "validate_build_environment", reject, raising=False)
	monkeypatch.setattr(module, "build_webui", lambda: pytest.fail("compilation started before preflight"))
	assert module.main() == 1
	assert "wrong pinned Python" in capsys.readouterr().out
