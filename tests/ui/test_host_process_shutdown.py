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


def test_discard_failed_host_preserves_startup_policy(host, monkeypatch):
	host.configure_host_lifecycle()
	calls = []
	host._host_process = SimpleNamespace(poll=lambda: None, pid=42,
		terminate=lambda: calls.append("terminate"), wait=lambda timeout: None)
	host.discard_failed_host()
	assert calls == ["terminate"]
	assert host._host_process is None
	monkeypatch.setattr(host, "get_host_executable_path", lambda: SimpleNamespace(exists=lambda: False))
	with pytest.raises(host.HostUnavailableError, match="not found"):
		host.start_host_if_needed()


@pytest.mark.parametrize("failure_stage", ["transport", "response"])
def test_failed_session_sync_allows_next_command_to_relaunch_host(host, monkeypatch, failure_stage):
	renderer_module = load_addon_module("ui.host_renderer", namespace="host_shutdown_testpkg")
	renderer = renderer_module.HostRenderer()
	started = []
	stopped = []

	def start():
		pid = len(started) + 1
		started.append(pid)
		host._host_process = SimpleNamespace(pid=pid, poll=lambda: None,
			terminate=lambda: stopped.append(pid), wait=lambda timeout: None)

	def send(message):
		if started == [1]:
			if failure_stage == "transport":
				raise TimeoutError("no host response")
			return b""
		command = renderer_module.HostCommand.from_json(message.decode("utf-8"))
		return renderer_module.HostResponse(request_id=command.id, status="ack").to_json().encode()

	monkeypatch.setattr(renderer_module, "start_host_if_needed", start)
	monkeypatch.setattr(renderer, "_probe_host", lambda: None)
	monkeypatch.setattr(renderer, "_transport", SimpleNamespace(send=send))

	with pytest.raises(renderer_module.HostUnavailableError) as failure:
		renderer._send_command("sync_session", {})
	assert failure.value.stage == failure_stage
	assert started == stopped == [1]
	assert host._host_process is None
	renderer._send_command("open_chat", {"title": "Chat"})
	assert started == [1, 2]
	assert stopped == [1]


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


@pytest.mark.parametrize("final_detail", ["webview_ready", "webview_failed"])
def test_health_check_waits_for_webview_not_just_the_command_pipe(host, monkeypatch, final_detail):
	renderer_module = load_addon_module("ui.host_renderer", namespace="host_shutdown_testpkg")
	renderer = renderer_module.HostRenderer()
	details = iter(["webview_starting", final_detail])

	def send(message):
		command = renderer_module.HostCommand.from_json(message.decode("utf-8"))
		return renderer_module.HostResponse(
			request_id=command.id, status="ack", message=next(details),
		).to_json().encode()

	monkeypatch.setattr(renderer, "_transport", SimpleNamespace(send=send))
	if final_detail == "webview_failed":
		with pytest.raises(renderer_module.HostUnavailableError, match="initialization failed"):
			renderer._probe_host()
	else:
		renderer._probe_host()
	assert next(details, None) is None
