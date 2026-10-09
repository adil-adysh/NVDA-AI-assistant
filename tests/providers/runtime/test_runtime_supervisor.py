# -*- coding: utf-8 -*-
"""Tests for the native RuntimeSupervisor PyO3 extension and LiteRT integration.

Validates the Python/Rust boundary:
- RuntimeStatus immutable snapshots
- Generation monotonicity
- Concurrent ensure_ready deduplication
- Child exit detection and deterministic error reporting
- Non-blocking read-only status queries
- Stale operation and config change protection
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import sys
import threading
from typing import Any, Iterator
import pytest

from tests.support import bootstrap

server_module = bootstrap.load_addon_module(
	"providers.runtime.server",
	namespace="test_runtime_supervisor_pkg",
)
LiteRTServerError = server_module.LiteRTServerError
LiteRTServerSupervisor = server_module.LiteRTServerSupervisor

llama_module = bootstrap.load_addon_module(
	"providers.runtime.llama_server",
	namespace="test_runtime_supervisor_pkg",
)
LlamaServerError = llama_module.LlamaServerError
LlamaServerSupervisor = llama_module.LlamaServerSupervisor

from runtime_supervisor import RuntimeStatus, RuntimeSupervisor  # noqa: E402


class _MockModelsHandler(BaseHTTPRequestHandler):
	def do_GET(self) -> None:
		self.send_response(200)
		self.send_header("Content-Type", "application/json")
		self.end_headers()
		self.wfile.write(b'{"data": [{"id": "mock-model"}]}')

	def log_message(self, format: str, *args: Any) -> None:
		pass


@pytest.fixture
def mock_compatible_port() -> Iterator[int]:
	server = HTTPServer(("127.0.0.1", 0), _MockModelsHandler)
	port = server.server_address[1]
	thread = threading.Thread(target=server.serve_forever, daemon=True)
	thread.start()
	try:
		yield port
	finally:
		server.shutdown()
		server.server_close()


def test_runtime_status_fields() -> None:
	"""RuntimeStatus snapshot provides frozen, typed properties."""
	supervisor = RuntimeSupervisor("litert-lm", "127.0.0.1", 9379)
	status = supervisor.status()

	assert isinstance(status, RuntimeStatus)
	assert status.state == "stopped"
	assert status.is_ready is False
	assert status.is_running is False
	assert status.is_adopted is False
	assert status.pid is None
	assert status.generation == 0
	assert status.error_message is None
	assert status.startup_identity is None
	assert status.running_model is None
	assert status.base_url == "http://127.0.0.1:9379"
	assert "RuntimeStatus" in repr(status)


def test_supervisor_adopt_fails_without_server() -> None:
	"""Adopt raises RuntimeError when no compatible server responds on endpoint."""
	supervisor = RuntimeSupervisor("litert-lm", "127.0.0.1", 9380)
	with pytest.raises(RuntimeError, match="No compatible litert-lm server responding"):
		supervisor.adopt()


def test_supervisor_adopt_and_stop(mock_compatible_port: int) -> None:
	"""Adopt transitions to ready_adopted without process handle; stop resets to stopped."""
	supervisor = RuntimeSupervisor("litert-lm", "127.0.0.1", mock_compatible_port)

	status = supervisor.adopt()
	assert status.state == "ready_adopted"
	assert status.is_ready is True
	assert status.is_running is False
	assert status.is_adopted is True
	assert status.generation == 1

	# Non-blocking query returns identical status
	queried = supervisor.status()
	assert queried.is_adopted is True
	assert queried.is_ready is True

	# Stop resets to stopped
	stopped = supervisor.stop()
	assert stopped.state == "stopped"
	assert stopped.is_ready is False
	assert stopped.is_adopted is False
	assert stopped.generation == 2


def test_supervisor_matches_startup_configuration(mock_compatible_port: int) -> None:
	"""matches_startup_configuration returns False when stopped or identity differs."""
	supervisor = RuntimeSupervisor("litert-lm", "127.0.0.1", mock_compatible_port)
	assert not supervisor.matches_startup_configuration("ident-1")

	supervisor.adopt()
	# Adopted runtime has no startup identity
	assert not supervisor.matches_startup_configuration("ident-1")


def test_supervisor_child_exit_immediately_detected() -> None:
	"""When child process exits immediately, ensure_ready returns deterministic error."""
	supervisor = RuntimeSupervisor("litert-lm", "127.0.0.1", 9382)
	python_exe = sys.executable

	# Spawn python that exits with code 42 immediately
	with pytest.raises(RuntimeError, match="exited unexpectedly with code 42"):
		supervisor.ensure_ready(
			python_exe,
			["-c", "import sys; sys.exit(42)"],
			{},
			"identity-crash",
			timeout_seconds=5.0,
		)

	status = supervisor.status()
	assert status.state == "failed"
	assert status.is_ready is False
	assert status.error_message is not None
	assert "exited unexpectedly with code 42" in status.error_message


def test_supervisor_simultaneous_ensure_ready_threads() -> None:
	"""Multiple threads calling ensure_ready concurrently deduplicate without deadlock."""
	supervisor = RuntimeSupervisor("litert-lm", "127.0.0.1", 9383)
	python_exe = sys.executable

	errors: list[Exception] = []

	def worker() -> None:
		try:
			# Child exits quickly; all threads should see the failure or wait
			supervisor.ensure_ready(
				python_exe,
				["-c", "import sys; sys.exit(7)"],
				{},
				"concurrent-ident",
				timeout_seconds=5.0,
			)
		except Exception as exc:
			errors.append(exc)

	threads = [threading.Thread(target=worker) for _ in range(5)]
	for t in threads:
		t.start()
	for t in threads:
		t.join(timeout=10.0)

	# All threads received the error without hanging or deadlocking
	assert len(errors) == 5
	for err in errors:
		assert "exited unexpectedly with code 7" in str(err)


def test_supervisor_restart_increments_generation(mock_compatible_port: int) -> None:
	"""Restart increments generation counter monotonically."""
	supervisor = RuntimeSupervisor("litert-lm", "127.0.0.1", mock_compatible_port)
	gen_0 = supervisor.status().generation

	supervisor.adopt()
	gen_1 = supervisor.status().generation
	assert gen_1 > gen_0

	supervisor.stop()
	gen_2 = supervisor.status().generation
	assert gen_2 > gen_1


def test_litert_server_supervisor_ensure_ready_wraps_errors(tmp_path: Path) -> None:
	"""LiteRTServerSupervisor.ensure_ready maps native RuntimeError to LiteRTServerError."""
	supervisor = LiteRTServerSupervisor(port=9385)
	# Mock server_python to return sys.executable
	supervisor._server_python = lambda: Path(sys.executable)  # type: ignore[method-assign]
	supervisor._litert_dir = lambda: tmp_path  # type: ignore[method-assign]

	# Point to a command that fails to bind / exits immediately
	# Native supervisor will fail because sys.executable is not a litert server
	with pytest.raises(LiteRTServerError):
		supervisor.ensure_ready(timeout=1.0)


def test_llama_server_supervisor_ensure_ready_wraps_errors() -> None:
	"""LlamaServerSupervisor.ensure_ready raises LlamaServerError when worker process is unavailable."""
	supervisor = LlamaServerSupervisor(port=8089)
	with pytest.raises(LlamaServerError, match="Worker process is not available"):
		supervisor.ensure_ready("mock-model", timeout=1.0)


def test_llama_runtime_status_fields() -> None:
	"""RuntimeStatus snapshot provides frozen, typed properties for llama-server."""
	supervisor = RuntimeSupervisor("llama-server", "127.0.0.1", 8089)
	status = supervisor.status()

	assert isinstance(status, RuntimeStatus)
	assert status.state == "stopped"
	assert status.is_ready is False
	assert status.is_running is False
	assert status.is_adopted is False
	assert status.pid is None
	assert status.generation == 0
	assert status.error_message is None
	assert status.startup_identity is None
	assert status.running_model is None
	assert status.base_url == "http://127.0.0.1:8089"
	assert "RuntimeStatus" in repr(status)


def test_llama_supervisor_adopt_tracks_running_model(mock_compatible_port: int) -> None:
	"""RuntimeSupervisor.adopt records the adopted running model ID for llama-server."""
	supervisor = RuntimeSupervisor("llama-server", "127.0.0.1", mock_compatible_port)
	status = supervisor.adopt(model_id="qwen-2.5-coder")

	assert status.state == "ready_adopted"
	assert status.is_ready is True
	assert status.is_running is False
	assert status.is_adopted is True
	assert status.running_model == "qwen-2.5-coder"
	assert status.generation == 1

	# Non-blocking query returns identical status
	queried = supervisor.status()
	assert queried.is_adopted is True
	assert queried.running_model == "qwen-2.5-coder"

	# Cleanup
	stopped = supervisor.stop()
	assert stopped.state == "stopped"
	assert stopped.is_ready is False
	assert stopped.is_adopted is False
	assert stopped.running_model is None


def test_llama_supervisor_matches_startup_configuration(mock_compatible_port: int) -> None:
	"""matches_startup_configuration returns False when stopped or identity differs."""
	supervisor = RuntimeSupervisor("llama-server", "127.0.0.1", mock_compatible_port)
	assert not supervisor.matches_startup_configuration("ident-1")

	supervisor.adopt(model_id="qwen-2.5-coder")
	assert not supervisor.matches_startup_configuration("ident-1")


def test_llama_multiple_endpoints_isolated(mock_compatible_port: int) -> None:
	"""Multiple native RuntimeSupervisor instances on distinct ports maintain separate lifecycle state."""
	sup1 = RuntimeSupervisor("llama-server", "127.0.0.1", mock_compatible_port)
	sup2 = RuntimeSupervisor("llama-server", "127.0.0.1", 8099)

	sup1.adopt("model-1")
	assert sup1.status().is_adopted is True
	assert sup1.status().running_model == "model-1"

	assert sup2.status().is_adopted is False
	assert sup2.status().running_model is None

	sup1.stop()


def test_llama_server_supervisor_delegates_to_injected_native() -> None:
	"""LlamaServerSupervisor delegates to native supervisor when explicitly injected."""
	native = RuntimeSupervisor("llama-server", "127.0.0.1", 8089)
	supervisor = LlamaServerSupervisor(port=8089, native_supervisor=native)
	status = supervisor.status()

	assert isinstance(status, RuntimeStatus)
	assert status.state == "stopped"
	assert supervisor.is_running is False
	assert supervisor.is_adopted is False
	assert supervisor.running_model is None
	assert supervisor.base_url == "http://127.0.0.1:8089"

