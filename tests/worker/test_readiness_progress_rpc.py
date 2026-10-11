import queue
import threading
from types import SimpleNamespace

from tests.support import load_addon_module

server_module = load_addon_module("worker.server", namespace="readiness_rpc")
client_module = load_addon_module("service.worker_client", namespace="readiness_rpc")


def test_disconnect_completes_pending_jobs_once():
	client = client_module.NamedPipeJobClient.__new__(client_module.NamedPipeJobClient)
	client._lock = threading.Lock()
	client._running = True
	client._snapshots = {"pending": SimpleNamespace(state=client_module.JobStatus.RUNNING, spec=SimpleNamespace(generation=4), progress=None, created_at_epoch_ms=0)}
	client._result_events = {"pending": threading.Event()}
	client._results = {}
	results = []
	client._result_callbacks = {"pending": [results.append]}
	client._fail_pending_jobs()
	client._fail_pending_jobs()
	assert client._result_events["pending"].is_set()
	assert len(results) == 1
	assert results[0].error_code == "WORKER_DISCONNECTED"
	assert results[0].generation == 4


def test_worker_readiness_stages_reach_client_before_final_response():
	frames = queue.Queue()
	stage_written = threading.Event()
	server = server_module.WorkerServer.__new__(server_module.WorkerServer)
	class Pipe:
		is_connected = True
		def write_frame(self, frame):
			frames.put(frame)
			if frame.get("type") == "runtime_progress":
				stage_written.set()
	server._cmd_server = Pipe()
	class Executor:
		def get_status(self):
			return {"state": "starting"}
		def ensure_ready(self, **_kwargs):
			assert stage_written.wait(2), "worker did not emit actual startup"
			return {"state": "ready_owned", "is_ready": True}
	server.get_litert_executor = lambda: Executor()
	threads = []
	class ClientPipe:
		is_connected = True
		def write_frame(self, frame):
			thread = threading.Thread(target=server._handle_command, args=(frame,))
			threads.append(thread)
			thread.start()
		def read_frame(self, timeout_seconds):
			return frames.get(timeout=timeout_seconds)
	client = client_module.NamedPipeWorkerClient(cmd_client=ClientPipe(), evt_client=SimpleNamespace())
	messages = []
	response = client.send_command({"type": "litert_ensure_ready", "report_readiness_progress": True}, on_progress=messages.append)
	for thread in threads:
		thread.join()
	assert response["success"]
	assert response["status"]["is_ready"]
	assert messages == ["Starting local AI server…"]
	assert frames.empty()
