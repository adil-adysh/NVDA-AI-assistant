"""Real HTTP/PyO3 contract; opt in with a freshly built llm_client DLL."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
from threading import Thread

import pytest


@pytest.mark.parametrize("provider", ["openai", "gemini", "ollama", "litert-lm", "llama-cpp-server"])
def test_draft_connection_through_native_http(provider):
	path = os.environ.get("NVDA_AI_LLM_CLIENT_PATH")
	if not path:
		pytest.skip("Set NVDA_AI_LLM_CLIENT_PATH to the freshly built llm_client DLL")
	requests = []
	class Handler(BaseHTTPRequestHandler):
		def do_GET(self):
			requests.append((self.path, self.headers.get("Authorization")))
			body = json.dumps({"data": [{"id": "gpt-6.2-sol", "capabilities": ["chat", "vision"]}]}).encode()
			self.send_response(200)
			self.send_header("Content-Length", str(len(body)))
			self.end_headers()
			self.wfile.write(body)
		def log_message(self, *_args):
			pass
	server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
	thread = Thread(target=server.serve_forever, daemon=True)
	thread.start()
	script = r'''
import importlib, importlib.util, importlib.machinery, sys
from tests.support import load_addon_module
path, port, provider_id = sys.argv[1:]
loader = importlib.machinery.ExtensionFileLoader("llm_client", path)
spec = importlib.util.spec_from_file_location("llm_client", path, loader=loader)
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
sys.modules["llm_client"] = native
adapter = load_addon_module("providers.adapters.openai_compat", namespace="http_connection_smoke")
config_module = importlib.import_module("http_connection_smoke.providers.config")
service = load_addon_module("service.provider_connection", namespace="http_connection_smoke")
config = config_module.OpenAICompatConfig(provider=provider_id, model_name="", timeout_seconds=30,
    enable_progress=False, num_ctx=0, max_retries=3, retry_backoff_seconds=1,
    generate_temperature=.2, generate_top_k=0, generate_top_p=1, generate_max_tokens=512,
    base_url=f"http://127.0.0.1:{port}", models_path="/draft/models", api_key="test-token")
assert service.ProviderConnectionService(provider_factory=adapter.OpenAICompatProvider).check(config) == 1
client = native.OpenAiClient(base_url=config.base_url, models_url=config.base_url + config.models_path)
assert client.list_models()[0]["capabilities"] == ["chat", "vision"]
print("native HTTP connection and metadata passed")
'''
	try:
		result = subprocess.run([sys.executable, "-c", script, str(Path(path).resolve()), str(server.server_port), provider],
			capture_output=True, text=True, timeout=20, check=False)
		assert result.returncode == 0, result.stderr
		assert requests == [("/draft/models", "Bearer test-token"), ("/draft/models", None)]
	finally:
		server.shutdown()
		server.server_close()
		thread.join(2)
