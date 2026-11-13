"""Loopback HTTP router fixture exercising the real urllib boundary."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading


@contextmanager
def router_http():
    class Router:
        payload = {"data": [{"id": "a", "status": {"value": "unloaded"}}]}
        status = 200
        legacy_status = 200
        chat_status = 200
        answer = "Fixture answer"
        requests = []

    state = Router()
    state.requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            state.requests.append(("GET", self.path, None))
            code = state.status if self.path == "/models" else state.legacy_status if self.path == "/v1/models" else 404
            self.send_response(code)
            self.end_headers()
            self.wfile.write(state.payload if isinstance(state.payload, bytes) else json.dumps(state.payload).encode())

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state.requests.append(("POST", self.path, body))
            if self.path == "/v1/chat/completions":
                self.send_response(state.chat_status)
                self.end_headers()
                if state.chat_status != 200:
                    self.wfile.write(b'{"error":{"message":"fixture failure"}}')
                elif body.get("stream"):
                    for text in ("Fixture ", "answer"):
                        chunk = {"choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]}
                        self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
                    self.wfile.write(b"data: [DONE]\n\n")
                else:
                    self.wfile.write(json.dumps({"choices": [{"index": 0, "message": {"role": "assistant", "content": state.answer}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}).encode())
                return
            state.payload = {"data": [{"id": body["model"], "status": {"value": "loaded" if self.path.endswith("load") and not self.path.endswith("unload") else "unloaded"}}]}
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.port = server.server_port
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
