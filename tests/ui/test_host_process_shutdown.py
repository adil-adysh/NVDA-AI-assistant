"""Shutdown permanently fences late host launches until a new app lifecycle."""
from types import SimpleNamespace

import pytest

from tests.support import load_addon_module


@pytest.fixture
def host(monkeypatch):
	module = load_addon_module("ui.host_process", namespace="host_shutdown_testpkg")
	monkeypatch.setattr(module, "_host_process", None)
	return module


def test_stop_without_process_rejects_late_launch_before_disk_access(host, monkeypatch):
	host.stop_host()
	monkeypatch.setattr(host, "get_host_executable_path", lambda: pytest.fail("late launch reached disk"))
	with pytest.raises(host.HostUnavailableError, match="shutdown"):
		host.start_host_if_needed()


def test_new_application_lifecycle_can_explicitly_enable_launches(host, monkeypatch):
	host.stop_host()
	host.configure_host_lifecycle()
	monkeypatch.setattr(host, "get_host_executable_path", lambda: SimpleNamespace(exists=lambda: False))
	with pytest.raises(host.HostUnavailableError, match="not found"):
		host.start_host_if_needed()


def test_kill_fallback_waits_for_exit_and_releases_handle(host):
	calls = []
	def wait(timeout):
		calls.append(("wait", timeout))
		if len(calls) == 2:
			raise TimeoutError()
	host._host_process = SimpleNamespace(poll=lambda: None,
		terminate=lambda: calls.append("terminate"), kill=lambda: calls.append("kill"), wait=wait)
	host.stop_host()
	assert calls == ["terminate", ("wait", 1.0), "kill", ("wait", 1.0)]
	assert host._host_process is None


def test_stop_terminates_real_owned_child(host):
	import subprocess
	import sys
	child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
		creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
	try:
		host._host_process = child
		host.stop_host()
		assert child.poll() is not None
	finally:
		if child.poll() is None:
			child.kill()
		child.wait(timeout=2)
