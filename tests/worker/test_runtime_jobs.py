"""Long runtime jobs must leave the control plane available."""
import threading
import pytest

from tests.support import load_addon_module

server_mod = load_addon_module("worker.server")
dto = load_addon_module("core.job.dto")


def test_shutdown_stops_initialized_runtimes_once_despite_cleanup_error():
	calls = []
	class Runtime:
		def __init__(self, name):
			self.name = name
		def shutdown(self, timeout_seconds):
			calls.append((self.name, timeout_seconds))
			if self.name == "litert":
				raise RuntimeError("stop failed")
	server = server_mod.WorkerServer(litert_executor=Runtime("litert"), llama_executor=Runtime("llama"))
	server._running = True
	server.shutdown()
	server.shutdown()
	assert calls == [("litert", 0.3), ("llama", 0.3)]
	for get_executor in (server.get_litert_executor, server.get_llama_executor):
		with pytest.raises(RuntimeError, match="shutdown"):
			get_executor()


def test_shutdown_does_not_create_idle_runtime_executors():
	server = server_mod.WorkerServer()
	server._running = True
	server.shutdown()
	assert server._litert_executor is None
	assert server._llama_executor is None
	with pytest.raises(RuntimeError, match="shutdown"):
		server.get_litert_executor()


@pytest.mark.parametrize("module_name,class_name", [("litert", "LiteRTWorkerExecutor"), ("llama", "LlamaWorkerExecutor")])
def test_executor_shutdown_fences_borrowed_native_owner_and_rejects_new_access(module_name, class_name):
	from types import SimpleNamespace
	module = load_addon_module(f"worker.executors.{module_name}")
	calls = []
	native = SimpleNamespace(fence_startup=lambda: calls.append("fence"),
		stop=lambda **kwargs: calls.append("stop"))
	executor = getattr(module, class_name)(supervisor=native)
	borrowed = executor._get_supervisor()
	executor.shutdown(timeout_seconds=0.3)
	assert borrowed is native
	assert calls == ["fence", "stop"]
	with pytest.raises(RuntimeError, match="shutdown"):
		executor._get_supervisor()


class Pipe:
	is_connected = True
	def __init__(self):
		self.frames = []
	def write_frame(self, frame):
		self.frames.append(frame)
	def close(self):
		self.is_connected = False


def test_slow_runtime_job_keeps_health_and_cancel_responsive():
	started, release = threading.Event(), threading.Event()
	class Runtime:
		def list_models(self, **kwargs):
			started.set()
			assert release.wait(3)
			return ["model"]
	server = server_mod.WorkerServer(litert_executor=Runtime(), max_workers=1)
	server._cmd_server = Pipe()
	spec = dto.JobSpec(job_id="slow", job_type="runtime_command", payload={"type": "litert_list_models"})
	try:
		server._handle_command(spec.to_dict())
		assert server._cmd_server.frames[-1]["type"] == "job_ack"
		assert started.wait(1)
		server._handle_command({"type": "worker_health_ping"})
		assert server._cmd_server.frames[-1]["type"] == "worker_health"
		server._handle_command({"type": "cancel_job", "job_id": "slow"})
		assert server._cmd_server.frames[-1]["accepted"]
	finally:
		release.set()
		server._executor.shutdown(wait=True)
		server._execution_lanes["litert"].shutdown(wait=True)
		server._control_executor.shutdown(wait=True)
	frames = list(server._event_queue.queue)
	assert frames[-1]["status"] == "cancelled"


def test_stale_generation_event_is_ignored():
	client_mod = load_addon_module("service.worker_client")
	client = client_mod.NamedPipeJobClient.__new__(client_mod.NamedPipeJobClient)
	client._lock = threading.Lock()
	spec = dto.JobSpec(job_id="same", job_type="echo", generation=2)
	client._snapshots = {"same": dto.JobSnapshot(spec=spec, state=dto.JobStatus.QUEUED)}
	client._results = {}
	client._result_events = {"same": threading.Event()}
	client._result_callbacks = {}
	client._handle_event_frame(dto.JobResult(job_id="same", status=dto.JobStatus.COMPLETED, generation=1).to_dict())
	assert not client._result_events["same"].is_set()
	assert not client._results


def test_terminal_event_survives_progress_congestion():
	server = server_mod.WorkerServer()
	try:
		for index in range(1100):
			server._emit_event({"type": "job_update", "job_id": str(index)})
		server._emit_event({"type": "job_result", "job_id": "terminal"})
		assert list(server._event_queue.queue)[-1]["job_id"] == "terminal"
	finally:
		server._executor.shutdown(wait=True)
		server._control_executor.shutdown(wait=True)


def test_real_pipes_stop_job_runs_with_execution_pool_busy():
	import uuid
	client_mod = load_addon_module("service.worker_client")
	started, release = threading.Event(), threading.Event()
	class Runtime:
		def list_models(self, **kwargs):
			started.set()
			assert release.wait(5)
			return ["model"]
		def stop(self, **kwargs):
			release.set()
			return {"state": "stopped", "is_running": False}
	key = uuid.uuid4().hex
	server = server_mod.WorkerServer(cmd_pipe_name=rf"\\.\pipe\jobs_cmd_{key}",
		evt_pipe_name=rf"\\.\pipe\jobs_evt_{key}", litert_executor=Runtime(), max_workers=1)
	server.start()
	client = client_mod.NamedPipeWorkerClient(cmd_pipe_name=server.cmd_pipe_name, evt_pipe_name=server.evt_pipe_name)
	result, errors = [], []
	def slow():
		try:
			result.append(client.send_command({"type": "litert_list_models"}, timeout=5))
		except Exception as error:
			errors.append(error)
	thread = threading.Thread(target=slow)
	try:
		client.connect()
		thread.start()
		assert started.wait(2)
		assert client.poll_health().is_healthy
		assert client.send_command({"type": "litert_stop"}, timeout=2)["success"]
		thread.join(2)
		assert not thread.is_alive() and not errors
		assert result[0]["models"] == ["model"]
	finally:
		release.set()
		thread.join(2)
		client.disconnect()
		server.shutdown()


def test_cancellation_terminates_real_cli_child(monkeypatch):
	import subprocess
	import sys
	process_mod = load_addon_module("worker.executors.process")
	cancel_mod = load_addon_module("core.job.cancellation")
	token = cancel_mod.CancellationToken("child")
	created, started = [], threading.Event()
	original = subprocess.Popen
	def spawn(*args, **kwargs):
		child = original(*args, **kwargs)
		created.append(child)
		started.set()
		return child
	monkeypatch.setattr(process_mod.subprocess, "Popen", spawn)
	errors = []
	def run():
		try:
			process_mod.run_cancellable([sys.executable, "-c", "import time; time.sleep(30)"],
				env=None, timeout=30, creationflags=0, token=token)
		except cancel_mod.JobCancelledError:
			errors.append("cancelled")
	thread = threading.Thread(target=run)
	thread.start()
	assert started.wait(2)
	token.cancel()
	thread.join(2)
	assert not thread.is_alive()
	assert errors == ["cancelled"] and created[0].poll() is not None


def test_unrelated_job_runs_while_runtime_lane_has_waiters():
	started, release = threading.Event(), threading.Event()
	class Runtime:
		def list_models(self, **kwargs):
			started.set()
			assert release.wait(3)
			return []
	server = server_mod.WorkerServer(litert_executor=Runtime(), max_workers=1)
	server._cmd_server = Pipe()
	try:
		for index in range(3):
			server._handle_command(dto.JobSpec(job_id=f"runtime-{index}", job_type="runtime_command",
				payload={"type": "litert_list_models"}).to_dict())
		assert started.wait(1)
		server._handle_command(dto.JobSpec(job_id="echo", job_type="echo", payload={}).to_dict())
		import time
		deadline = time.monotonic() + 1
		while not any(frame.get("job_id") == "echo" for frame in list(server._event_queue.queue)):
			assert time.monotonic() < deadline
			time.sleep(0.01)
	finally:
		release.set()
		server._executor.shutdown(wait=True)
		server._control_executor.shutdown(wait=True)
		for lane in getattr(server, "_execution_lanes", {}).values():
			lane.shutdown(wait=True)


def test_pipe_write_deadline_when_peer_does_not_read():
	import uuid
	transport = load_addon_module("worker.ipc.transport")
	name = rf"\\.\pipe\write_deadline_{uuid.uuid4().hex}"
	server, client = transport.NamedPipeServer(name), transport.NamedPipeClient(name)
	errors = []
	connected = threading.Event()
	def writer():
		try:
			client.connect(timeout_seconds=2)
			connected.set()
			client.write_raw(b"x" * (1024 * 1024), timeout_seconds=0.1)
		except Exception as error:
			errors.append(error)
	thread = threading.Thread(target=writer)
	try:
		thread.start()
		assert server.accept_connection(timeout_seconds=2)
		assert connected.wait(1)
		thread.join(1)
		assert not thread.is_alive()
		assert len(errors) == 1 and isinstance(errors[0], TimeoutError)
	finally:
		server.close()
		thread.join(2)
		client.close()


def test_cancelled_startup_cannot_leave_a_late_server_running():
	preparing, release = threading.Event(), threading.Event()
	class Runtime:
		running = False
		generation = 0
		def get_status(self):
			return {"state": "ready_owned" if self.running else "stopped",
				"is_running": self.running, "is_adopted": False, "generation": self.generation}
		def ensure_ready(self, **kwargs):
			preparing.set()
			assert release.wait(2)
			# Deliberately models native launch after earlier cancellation.
			self.running = True
			self.generation += 1
			return self.get_status()
		def stop(self, **kwargs):
			self.running = False
			self.generation += 1
			return self.get_status()
	runtime = Runtime()
	server = server_mod.WorkerServer(litert_executor=runtime)
	server._cmd_server = Pipe()
	try:
		server._handle_command(dto.JobSpec(job_id="startup", job_type="runtime_command",
			payload={"type": "litert_ensure_ready"}).to_dict())
		assert preparing.wait(1)
		server._handle_command({"type": "cancel_job", "job_id": "startup"})
		release.set()
		server._execution_lanes["litert"].shutdown(wait=True)
		assert not runtime.running
		assert list(server._event_queue.queue)[-1]["status"] == "cancelled"
	finally:
		release.set()
		server._executor.shutdown(wait=True)
		server._control_executor.shutdown(wait=True)
		for lane in server._execution_lanes.values():
			lane.shutdown(wait=True)


def test_passive_status_never_waits_for_worker_response():
	provider = load_addon_module("providers.runtime.server", namespace="passive_status_jobs")
	class Client:
		is_connected = True
		def get_runtime_status_snapshot(self, runtime):
			return {"state": "starting", "is_running": False, "generation": 1}
		def send_command(self, *args, **kwargs):
			raise AssertionError("Passive status performed blocking IPC")
	assert provider.LiteRTServerSupervisor(worker_client=Client()).status().state == "starting"


def test_stop_submission_has_reserved_capacity_under_progress_backpressure():
	stopped = threading.Event()
	class Runtime:
		def stop(self, **kwargs):
			stopped.set()
			return {"state": "stopped"}
	server = server_mod.WorkerServer(litert_executor=Runtime())
	server._cmd_server = Pipe()
	try:
		for index in range(1000):
			server._emit_event({"type": "job_update", "job_id": str(index)})
		server._handle_command(dto.JobSpec(job_id="stop", job_type="runtime_command", payload={"type": "litert_stop"}).to_dict())
		assert server._cmd_server.frames[-1]["status"] == "accepted"
		assert stopped.wait(1)
	finally:
		server._executor.shutdown(wait=True)
		server._control_executor.shutdown(wait=True)
		for lane in server._execution_lanes.values():
			lane.shutdown(wait=True)


def test_catalog_fence_control_jobs_bypass_busy_runtime_lane():
    started, release, fenced = threading.Event(), threading.Event(), threading.Event()
    class Runtime:
        def list_models(self, **kwargs):
            started.set()
            assert release.wait(3)
            return []
        def pause_startup(self):
            fenced.set()
            return 23
    server = server_mod.WorkerServer(llama_executor=Runtime(), max_workers=1)
    server._cmd_server = Pipe()
    try:
        server._handle_command(dto.JobSpec(job_id="load", job_type="runtime_command",
            payload={"type": "llama_list_models"}).to_dict())
        assert started.wait(1)
        server._handle_command(dto.JobSpec(job_id="fence", job_type="runtime_command",
            payload={"type": "llama_pause_startup"}).to_dict())
        assert server._cmd_server.frames[-1]["type"] == "job_ack"
        assert fenced.wait(1)
        server._handle_command({"type": "worker_health_ping"})
        assert server._cmd_server.frames[-1]["type"] == "worker_health"
    finally:
        release.set()
        server._executor.shutdown(wait=True)
        server._execution_lanes["llama"].shutdown(wait=True)
        server._control_executor.shutdown(wait=True)
    frames = list(server._event_queue.queue)
    result = next(frame for frame in frames if frame.get("type") == "job_result" and frame["job_id"] == "fence")
    assert result["status"] == "completed"
    assert result["result_data"]["token"] == 23
