from __future__ import annotations

import sys
from threading import Event
import threading
from concurrent.futures import ThreadPoolExecutor
import pytest

from tests.support.bootstrap import load_addon_module

mcp_manager = load_addon_module("worker.mcp_manager")
runtime_commands = load_addon_module("worker.runtime_commands")
worker_server_module = load_addon_module("worker.server")


def test_manager_client_negotiates_and_correlates_concurrent_replies():
    script = (
        "import json,sys,time\n"
        "for line in sys.stdin:\n"
        " r=json.loads(line); op=r['op']; rid=r['id']\n"
        " if op == 'hello': body={'ok': True, 'protocol_version': 1}\n"
        " else:\n"
        "  time.sleep(float(r.get('delay', 0)))\n"
        "  body={'ok': True, 'op': op}\n"
        " print(json.dumps({'id':rid, **body}), flush=True)\n"
    )
    client = mcp_manager.McpManagerClient((sys.executable, "-u", "-c", script))
    try:
        client.start()
        with ThreadPoolExecutor(max_workers=2) as pool:
            slow = pool.submit(client.request, {"op": "slow", "delay": 0.08}, timeout=2)
            fast = pool.submit(client.request, {"op": "fast"}, timeout=2)
            assert fast.result()["op"] == "fast"
            assert slow.result()["op"] == "slow"
    finally:
        client.close()


def test_manager_exit_during_invoke_marks_remote_outcome_uncertain():
	script = (
		"import json,sys\n"
		"for line in sys.stdin:\n"
		" r=json.loads(line)\n"
		" if r['op']=='hello': print(json.dumps({'id':r['id'],'ok':True,'protocol_version':1}),flush=True)\n"
		" else: sys.exit(17)\n"
	)
	client = mcp_manager.McpManagerClient((sys.executable, "-u", "-c", script))
	try:
		client.start()
		with pytest.raises(mcp_manager.McpManagerError) as caught:
			client.request({"op": "invoke"}, timeout=2)
		assert caught.value.uncertain is True
	finally:
		client.close()


def test_worker_replaces_failed_manager_with_lazy_client_without_replay():
	class FailedManager:
		closed = False

		@property
		def failed(self):
			return True

		def close(self, *, timeout):
			self.closed = True

	worker = object.__new__(worker_server_module.WorkerServer)
	worker._executor_lock = threading.RLock()
	worker._shutdown_event = Event()
	failed_manager = FailedManager()
	worker._mcp_manager_client = failed_manager

	recovered = worker.get_mcp_manager()

	assert failed_manager.closed is True
	assert isinstance(recovered, mcp_manager.McpManagerClient)
	assert recovered is not failed_manager
	assert recovered._started is False
	assert recovered._pending == {}


def test_manager_startup_handshake_observes_cancellation():
	script = (
		"import json,sys,time\n"
		"for line in sys.stdin:\n"
		" r=json.loads(line); time.sleep(5)\n"
		" print(json.dumps({'id':r['id'],'ok':True,'protocol_version':1}),flush=True)\n"
	)
	client = mcp_manager.McpManagerClient((sys.executable, "-u", "-c", script))
	cancel = Event()
	hello_started = Event()
	original_send = client._send_request
	def send_request(command, **kwargs):
		if command.get("op") == "hello":
			hello_started.set()
		return original_send(command, **kwargs)
	client._send_request = send_request
	try:
		with ThreadPoolExecutor(max_workers=1) as pool:
			startup = pool.submit(client.start, timeout=3, cancellation_requested=cancel.is_set)
			assert hello_started.wait(1)
			cancel.set()
			with pytest.raises(mcp_manager.McpManagerError) as caught:
				startup.result(timeout=2)
		assert caught.value.category == "cancelled"
		assert client.running is False
	finally:
		client.close()


def test_oversized_requests_do_not_consume_pending_capacity():
	script = (
		"import json,sys\n"
		"for line in sys.stdin:\n"
		" r=json.loads(line); body={'ok':True,'protocol_version':1} if r['op']=='hello' else {'ok':True}\n"
		" print(json.dumps({'id':r['id'],**body}),flush=True)\n"
	)
	client = mcp_manager.McpManagerClient((sys.executable, "-u", "-c", script))
	try:
		client.start()
		large_value = "x" * mcp_manager.MAX_FRAME_BYTES
		for _ in range(mcp_manager.MAX_PENDING_REQUESTS):
			with pytest.raises(mcp_manager.McpManagerError) as caught:
				client.request({"op": "status", "padding": large_value}, timeout=1)
			assert caught.value.category == "message_too_large"
		assert len(client._pending) == 0
		assert client.request({"op": "status"}, timeout=1)["ok"] is True
	finally:
		client.close()


def test_event_queue_overflow_delivers_a_resync_marker():
    client = mcp_manager.McpManagerClient((sys.executable, "-c", "pass"))
    for index in range(client._events.maxsize):
        client._events.put_nowait({"event": "tool_list_changed", "index": index})

    client._deliver_event({"event": "tool_list_changed", "server_id": "server-a"})

    assert client.next_event(timeout=0) == {
        "event": "resync_required",
        "reason": "worker_event_queue_overflow",
    }
    assert client.next_event(timeout=0) is None


def test_concurrent_start_waits_for_successful_handshake():
    script = (
        "import json,sys,time\n"
        "ready=False\n"
        "for line in sys.stdin:\n"
        " r=json.loads(line); op=r['op']; rid=r['id']\n"
        " if op == 'hello': time.sleep(0.15); ready=True; body={'ok':True,'protocol_version':1}\n"
        " else: body={'ok':ready}\n"
        " print(json.dumps({'id':rid,**body}),flush=True)\n"
    )
    client = mcp_manager.McpManagerClient((sys.executable, "-u", "-c", script))
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(client.start)
            second = pool.submit(client.start)
            first.result(timeout=2)
            second.result(timeout=2)
        assert client.request({"op": "status"}, timeout=2)["ok"] is True
    finally:
        client.close()


def test_concurrent_start_observes_handshake_failure():
    script = (
        "import json,sys,time\n"
        "for line in sys.stdin:\n"
        " r=json.loads(line); time.sleep(0.15)\n"
        " print(json.dumps({'id':r['id'],'ok':False,'protocol_version':99}),flush=True)\n"
    )
    client = mcp_manager.McpManagerClient((sys.executable, "-u", "-c", script))
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            starts = [pool.submit(client.start) for _ in range(2)]
            errors = []
            for start in starts:
                try:
                    start.result(timeout=2)
                except mcp_manager.McpManagerError as error:
                    errors.append(error)
        assert len(errors) == 2
        with pytest.raises(mcp_manager.McpManagerError):
            client.request({"op": "status"})
    finally:
        client.close()


class _FakeManager:
    def __init__(self):
        self.started = False
        self.commands = []
        self.cancel_check = None
        self.running = True

    def start(self, *, timeout=10.0, cancellation_requested=None):
        self.started = True
        self.start_timeout = timeout

    def request(self, command, *, timeout, cancellation_requested=None):
        self.commands.append(command)
        self.cancel_check = cancellation_requested
        self.request_timeout = timeout
        return {"ok": True, "server_id": command.get("server_id")}


class _FakeWorker:
    def __init__(self):
        self._mcp_manager_client = None
        self.manager = _FakeManager()
        self.created_manager = False

    def get_mcp_manager(self):
        self.created_manager = True
        return self.manager


def test_worker_mcp_status_is_passive_and_connect_uses_manager_owner():
    worker = _FakeWorker()
    frames = []
    runtime_commands.execute_runtime_command(
        worker, {"type": "mcp_manager_status"}, frames.append
    )
    assert worker.created_manager is False
    assert frames[0]["reply"]["manager_state"] == "stopped"

    runtime_commands.execute_runtime_command(
        worker,
        {"type": "mcp_connect_stdio", "server_id": "local", "executable": "tool.exe", "args": [], "env": {}},
        frames.append,
    )
    assert worker.manager.started is True
    assert worker.manager.commands[0]["op"] == "connect_stdio"
    assert worker.manager.commands[0]["server_id"] == "local"


def test_worker_forwards_http_bearer_token_only_to_manager_command():
    worker = _FakeWorker()
    frames = []
    runtime_commands.execute_runtime_command(
        worker,
        {"type": "mcp_connect_http", "server_id": "remote", "url": "https://mcp.example.test", "auth_token": "protected-token"},
        frames.append,
    )
    assert worker.manager.commands[0] == {
        "op": "connect_http", "server_id": "remote", "url": "https://mcp.example.test", "auth_token": "protected-token",
    }
    assert frames[0]["success"] is True


def test_worker_mcp_invoke_forwards_identity_deadline_and_cancellation():
    worker = _FakeWorker()
    frames = []
    cancelled = False
    runtime_commands.execute_runtime_command(
        worker,
        {
            "type": "mcp_invoke", "server_id": "local", "manager_session_id": "session-1", "server_incarnation": 4,
            "catalog_generation": 7, "tool_name": "read", "arguments": {"x": 1},
            "timeout_ms": 9000, "tool_call_id": "call-9", "timeout_seconds": 9,
        },
        frames.append,
        cancellation_requested=lambda: cancelled,
    )
    assert worker.manager.commands[0] | {"timeout_ms": 9000} == {
        "op": "invoke", "server_id": "local", "manager_session_id": "session-1", "server_incarnation": 4,
        "catalog_generation": 7, "tool_name": "read", "arguments": {"x": 1},
        "timeout_ms": 9000, "tool_call_id": "call-9",
    }
    assert 1 <= worker.manager.commands[0]["timeout_ms"] <= 9000
    assert worker.manager.cancel_check is not None
    assert worker.manager.cancel_check() is False
    assert frames[0]["reply"]["ok"] is True


def test_worker_mcp_deadline_includes_manager_startup(monkeypatch):
    worker = _FakeWorker()
    frames = []
    clock = iter((10.0, 10.0, 10.25))
    monkeypatch.setattr(runtime_commands.time, "monotonic", lambda: next(clock))
    runtime_commands.execute_runtime_command(
        worker,
        {
            "type": "mcp_invoke", "server_id": "local", "manager_session_id": "session-1",
            "server_incarnation": 4, "catalog_generation": 7, "tool_name": "read",
            "arguments": {}, "timeout_ms": 1000, "timeout_seconds": 1,
        },
        frames.append,
    )
    assert worker.manager.start_timeout == 1
    assert worker.manager.request_timeout == 0.75
    assert worker.manager.commands[0]["timeout_ms"] == 750


def test_cancelled_connect_is_not_dispatched_and_cleans_up_after_timeout():
    worker = _FakeWorker()
    frames = []
    runtime_commands.execute_runtime_command(
        worker,
        {"type": "mcp_connect_stdio", "server_id": "local", "executable": "tool.exe", "timeout_seconds": 1},
        frames.append,
        cancellation_requested=lambda: True,
    )
    assert worker.manager.commands[0]["op"] == "disconnect"
    assert worker.manager.commands[0]["server_id"] == "local"
    assert frames[0]["error_code"] == "cancelled"
