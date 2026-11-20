"""Exercise newly built native shutdown through both real worker executors."""
import sys
import json
import ctypes
import importlib.machinery
import importlib.util
from pathlib import Path
import socket
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"data": [{"id": "smoke"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if len(sys.argv) > 1 and sys.argv[1] == "--serve":
    HTTPServer(("127.0.0.1", int(sys.argv[2])), Handler).serve_forever()
    raise SystemExit()

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))
from tests.support import load_addon_module  # noqa: E402

dll = root / "runtime_supervisor/target/x86_64-pc-windows-msvc/debug/runtime_supervisor.dll"
loader = importlib.machinery.ExtensionFileLoader("runtime_supervisor", str(dll))
spec = importlib.util.spec_from_file_location("runtime_supervisor", dll, loader=loader)
native = importlib.util.module_from_spec(spec)
loader.exec_module(native)
kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.OpenProcess.restype = ctypes.c_void_p
kernel.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
kernel.CloseHandle.argtypes = (ctypes.c_void_p,)

for module_name, class_name in (("litert", "LiteRTWorkerExecutor"), ("llama", "LlamaWorkerExecutor")):
    module = load_addon_module(f"worker.executors.{module_name}")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    owner = native.RuntimeSupervisor(module_name, "127.0.0.1", port)
    executor = getattr(module, class_name)(port=port, supervisor=owner)
    handle = None
    try:
        status = owner.ensure_ready(sys.executable, [str(Path(__file__).resolve()), "--serve", str(port)], {}, "smoke", timeout_seconds=10)
        assert status.is_running and not status.is_adopted
        handle = kernel.OpenProcess(0x100000, False, status.pid)
        assert handle
        borrowed = executor._get_supervisor()
        executor.shutdown(timeout_seconds=0.3)
        assert kernel.WaitForSingleObject(handle, 2000) == 0, "owned child survived shutdown"
        try:
            borrowed.ensure_ready("invalid", [], {}, "late", timeout_seconds=0.1)
        except RuntimeError as error:
            assert "shutdown" in str(error)
        else:
            raise AssertionError("late launch succeeded")
    finally:
        owner.shutdown()
        if handle:
            kernel.CloseHandle(handle)

    remote = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=remote.serve_forever, daemon=True)
    thread.start()
    try:
        port = remote.server_address[1]
        adopted = native.RuntimeSupervisor(module_name, "127.0.0.1", port)
        assert adopted.adopt().is_adopted
        getattr(module, class_name)(port=port, supervisor=adopted).shutdown(timeout_seconds=0.3)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=2) as response:
            assert response.status == 200
    finally:
        remote.shutdown()
        remote.server_close()
        thread.join(2)
    print(f"{module_name}: owned child exited, borrowed launch rejected, external server preserved")
