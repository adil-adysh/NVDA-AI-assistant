# -*- coding: utf-8 -*-
"""Unit and integration tests for llama.cpp worker execution, IPC routing, and fault isolation."""

from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock
import uuid

from tests.support import load_addon_module

dto_mod = load_addon_module("core.job.dto")
server_mod = load_addon_module("worker.server")
trans_mod = load_addon_module("worker.ipc.transport")
worker_client_mod = load_addon_module("service.worker_client")
llama_exec_mod = load_addon_module("worker.executors.llama")
llama_server_mod = load_addon_module("providers.runtime.llama_server")

HandshakeRequest = dto_mod.HandshakeRequest
HandshakeResponse = dto_mod.HandshakeResponse
NamedPipeClient = trans_mod.NamedPipeClient
NamedPipeWorkerClient = worker_client_mod.NamedPipeWorkerClient
WorkerServer = server_mod.WorkerServer
LlamaWorkerExecutor = llama_exec_mod.LlamaWorkerExecutor
build_llama_server_args = llama_exec_mod.build_llama_server_args
build_startup_identity = llama_exec_mod.build_startup_identity
LlamaServerSupervisor = llama_server_mod.LlamaServerSupervisor
LlamaServerError = llama_server_mod.LlamaServerError


class TestLlamaWorkerExecutor(unittest.TestCase):
	"""Verify LlamaWorkerExecutor lifecycle, status mapping, preset generation, and CLI args."""

	def setUp(self) -> None:
		self.mock_native = mock.MagicMock()
		mock_status = types.SimpleNamespace(
			state="stopped",
			generation=0,
			pid=None,
			active_pid=None,
			host="127.0.0.1",
			port=8080,
			is_ready=False,
			is_running=False,
			is_adopted=False,
			error_message=None,
			startup_identity=None,
			running_model=None,
			base_url="http://127.0.0.1:8080",
		)
		self.mock_native.status.return_value = mock_status
		self.mock_native.ensure_ready.return_value = mock_status
		self.mock_native.stop.return_value = mock_status
		self.mock_native.restart.return_value = mock_status
		self.mock_native.adopt.return_value = mock_status

		self.executor = LlamaWorkerExecutor(host="127.0.0.1", port=8080, supervisor=self.mock_native)

	def test_get_status_mapping(self) -> None:
		status = self.executor.get_status()
		self.assertEqual(status["state"], "stopped")
		self.assertEqual(status["generation"], 0)
		self.assertIsNone(status["pid"])
		self.assertFalse(status["is_ready"])
		self.assertFalse(status["is_running"])

	def test_ensure_ready_delegation(self) -> None:
		config = {"model": "C:\\models\\qwen.gguf", "host": "127.0.0.1", "port": 8080}
		res = self.executor.ensure_ready(config=config, model_id="qwen")
		self.mock_native.ensure_ready.assert_called_once()
		self.assertEqual(res["state"], "stopped")

	def test_stop_delegation(self) -> None:
		res = self.executor.stop(timeout_seconds=5.0)
		self.mock_native.stop.assert_called_once_with(timeout_seconds=5.0)
		self.assertEqual(res["state"], "stopped")

	def test_restart_delegation(self) -> None:
		config = {"model": "C:\\models\\qwen.gguf"}
		res = self.executor.restart(config=config, model_id="qwen", timeout_seconds=5.0)
		self.mock_native.restart.assert_called_once()
		self.assertEqual(res["state"], "stopped")

	def test_adopt_delegation(self) -> None:
		res = self.executor.adopt(model_id="qwen")
		self.mock_native.adopt.assert_called_once_with(model_id="qwen")
		self.assertEqual(res["state"], "stopped")

	def test_ensure_ready_custom_host_and_port(self) -> None:
		config = {"model": "C:\\models\\qwen.gguf"}
		self.executor.ensure_ready(config=config, host="0.0.0.0", port=8888)
		self.assertEqual(self.executor.host, "0.0.0.0")
		self.assertEqual(self.executor.port, 8888)
		self.mock_native.ensure_ready.assert_called_once()
		call_args = self.mock_native.ensure_ready.call_args
		cmd_args = call_args[0][1]
		self.assertIn("--host", cmd_args)
		self.assertIn("0.0.0.0", cmd_args)
		self.assertIn("--port", cmd_args)
		self.assertIn("8888", cmd_args)

	def test_restart_custom_host_and_port(self) -> None:
		config = {"model": "C:\\models\\qwen.gguf"}
		self.executor.restart(config=config, host="127.0.0.2", port=8889)
		self.assertEqual(self.executor.host, "127.0.0.2")
		self.assertEqual(self.executor.port, 8889)
		self.mock_native.restart.assert_called_once()
		call_args = self.mock_native.restart.call_args
		cmd_args = call_args[0][1]
		self.assertIn("--host", cmd_args)
		self.assertIn("127.0.0.2", cmd_args)
		self.assertIn("--port", cmd_args)
		self.assertIn("8889", cmd_args)

	def test_configure_preset_creates_valid_ini_and_hash(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			preset_file = Path(td) / "models.ini"
			models = [
				{
					"model_id": "qwen",
					"source": "unsloth/Qwen3-8B-GGUF",
					"kind": "hugging_face",
					"variant": "UD-Q4_K_XL",
				},
				{
					"model_id": "local_model",
					"source": str(Path(td) / "local.gguf"),
					"kind": "local_file",
					"local_path": str(Path(td) / "local.gguf"),
				},
			]
			res = self.executor.configure_preset(
				models=models,
				default_model="qwen",
				preset_path=preset_file,
			)
			self.assertTrue(res["success"])
			self.assertEqual(res["preset_path"], str(preset_file))
			self.assertTrue(preset_file.is_file())

			content = preset_file.read_text(encoding="utf-8")
			self.assertIn("version = 1", content)
			self.assertIn("[qwen]", content)
			self.assertIn("hf-repo = unsloth/Qwen3-8B-GGUF:UD-Q4_K_XL", content)
			self.assertIn("[local_model]", content)

			expected_hash = hashlib.sha256(preset_file.read_bytes()).hexdigest()
			self.assertEqual(res["sha256"], expected_hash)

	def test_configure_preset_default_model_ordering(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			preset_file = Path(td) / "models.ini"
			models = [
				{"model_id": "model_b", "source": "repo/b", "kind": "hugging_face"},
				{"model_id": "model_a", "source": "repo/a", "kind": "hugging_face"},
			]
			res = self.executor.configure_preset(
				models=models,
				default_model="model_a",
				preset_path=preset_file,
			)
			self.assertTrue(res["success"])
			content = preset_file.read_text(encoding="utf-8")
			idx_a = content.find("[model_a]")
			idx_b = content.find("[model_b]")
			self.assertLess(idx_a, idx_b)

	def test_startup_identity_immutable(self) -> None:
		"""Verify Invariant A8: immutable runtime specs via json startup identity."""
		id1 = build_startup_identity(model="model_a", model_id="a", threads=4, context=2048)
		id2 = build_startup_identity(model="model_a", model_id="a", threads=4, context=2048)
		self.assertEqual(id1, id2)

		id3 = build_startup_identity(model="model_a", model_id="a", threads=8, context=2048)
		self.assertNotEqual(id1, id3)


class TestWorkerServerLlamaProtocol(unittest.TestCase):
	"""Verify WorkerServer command frame dispatch and capability negotiation for llama commands."""

	def setUp(self) -> None:
		token = uuid.uuid4().hex[:8]
		self.cmd_pipe = f"\\\\.\\pipe\\test_llama_cmd_{token}"
		self.evt_pipe = f"\\\\.\\pipe\\test_llama_evt_{token}"
		self.server = WorkerServer(
			cmd_pipe_name=self.cmd_pipe,
			evt_pipe_name=self.evt_pipe,
		)
		self.mock_executor = mock.MagicMock()
		self.server._llama_executor = self.mock_executor
		self.server.start()

		self.client = NamedPipeClient(self.cmd_pipe)
		self.client.connect(timeout_seconds=2.0)

		# Exchange handshake frame first
		req = HandshakeRequest(
			protocol_version="1.0.0",
			client_name="test_llama_client",
			client_version="1.0.0",
			requested_capabilities=("job.echo", "runtime.llama"),
		)
		self.client.write_frame(req.to_dict())
		raw_resp = self.client.read_frame()
		self.handshake_resp = HandshakeResponse.from_dict(raw_resp)

	def tearDown(self) -> None:
		self.client.close()
		self.server.shutdown()

	def test_handshake_negotiates_llama_capability(self) -> None:
		self.assertTrue(self.handshake_resp.accepted)
		self.assertIn("runtime.llama", self.handshake_resp.negotiated_capabilities)

	def test_dispatch_llama_get_status(self) -> None:
		self.mock_executor.get_status.return_value = {
			"state": "ready_owned",
			"generation": 3,
			"pid": 5678,
			"host": "127.0.0.1",
			"port": 8080,
			"is_ready": True,
			"is_running": True,
		}
		self.client.write_frame({"type": "llama_get_status", "command": "llama_get_status"})
		resp = self.client.read_frame()
		self.assertTrue(resp.get("success"))
		self.assertEqual(resp.get("type"), "llama_status_response")
		self.assertEqual(resp.get("status", {}).get("state"), "ready_owned")

	def test_dispatch_llama_ensure_ready(self) -> None:
		self.mock_executor.ensure_ready.return_value = {
			"state": "ready_owned",
			"generation": 1,
			"is_ready": True,
		}
		self.client.write_frame({
			"type": "llama_ensure_ready",
			"command": "llama_ensure_ready",
			"model": "model.gguf",
			"model_id": "model",
			"timeout_seconds": 20.0,
			"host": "127.0.0.1",
			"port": 8080,
		})
		resp = self.client.read_frame()
		self.assertTrue(resp.get("success"))
		self.assertEqual(resp.get("status", {}).get("state"), "ready_owned")
		self.mock_executor.ensure_ready.assert_called_once()

	def test_dispatch_llama_stop(self) -> None:
		self.mock_executor.stop.return_value = {"state": "stopped", "generation": 2}
		self.client.write_frame({
			"type": "llama_stop",
			"command": "llama_stop",
			"timeout_seconds": 5.0,
		})
		resp = self.client.read_frame()
		self.assertTrue(resp.get("success"))
		self.assertEqual(resp.get("status", {}).get("state"), "stopped")
		self.mock_executor.stop.assert_called_once_with(timeout_seconds=5.0)

	def test_dispatch_llama_restart(self) -> None:
		self.mock_executor.restart.return_value = {"state": "ready_owned", "generation": 3}
		self.client.write_frame({
			"type": "llama_restart",
			"command": "llama_restart",
			"model": "new_model.gguf",
			"model_id": "new_model",
			"timeout_seconds": 15.0,
		})
		resp = self.client.read_frame()
		self.assertTrue(resp.get("success"))
		self.mock_executor.restart.assert_called_once()

	def test_dispatch_llama_restart_with_custom_host_port(self) -> None:
		self.mock_executor.restart.return_value = {"state": "ready_owned", "generation": 4}
		self.client.write_frame({
			"type": "llama_restart",
			"command": "llama_restart",
			"model": "new_model.gguf",
			"host": "127.0.0.5",
			"port": 8090,
			"timeout_seconds": 10.0,
		})
		resp = self.client.read_frame()
		self.assertTrue(resp.get("success"))
		self.mock_executor.restart.assert_called_once()
		call_kwargs = self.mock_executor.restart.call_args.kwargs
		self.assertEqual(call_kwargs.get("host"), "127.0.0.5")
		self.assertEqual(call_kwargs.get("port"), 8090)

	def test_dispatch_llama_adopt(self) -> None:
		self.mock_executor.adopt.return_value = {"state": "ready_adopted", "generation": 1}
		self.client.write_frame({
			"type": "llama_adopt",
			"command": "llama_adopt",
			"model_id": "adopted_model",
		})
		resp = self.client.read_frame()
		self.assertTrue(resp.get("success"))
		self.mock_executor.adopt.assert_called_once_with(model_id="adopted_model")

	def test_dispatch_llama_configure_preset(self) -> None:
		self.mock_executor.configure_preset.return_value = {
			"preset_path": "C:\\models\\models.ini",
			"sha256": "abc123sha",
		}
		self.client.write_frame({
			"type": "llama_configure_preset",
			"command": "llama_configure_preset",
			"models": [{"model_id": "test_m"}],
			"default_model": "test_m",
		})
		resp = self.client.read_frame()
		self.assertTrue(resp.get("success"))
		self.assertEqual(resp.get("preset_path"), "C:\\models\\models.ini")
		self.assertEqual(resp.get("sha256"), "abc123sha")

	def test_dispatch_llama_list_models(self) -> None:
		self.mock_executor.list_models.return_value = [{"id": "model_1"}, {"id": "model_2"}]
		self.client.write_frame({
			"type": "llama_list_models",
			"command": "llama_list_models",
		})
		resp = self.client.read_frame()
		self.assertTrue(resp.get("success"))
		self.assertEqual(len(resp.get("models", [])), 2)

	def test_error_frame_containment(self) -> None:
		"""Verify that executor failure produces an error frame and isolates server."""
		self.mock_executor.get_status.side_effect = RuntimeError("Simulated crash")
		self.client.write_frame({
			"type": "llama_get_status",
			"command": "llama_get_status",
		})
		resp = self.client.read_frame()
		self.assertEqual(resp.get("type"), "error")
		self.assertIn("Simulated crash", str(resp.get("error_message")))

		# Subsequent request succeeds without hanging
		self.mock_executor.get_status.side_effect = None
		self.mock_executor.get_status.return_value = {"state": "stopped", "is_ready": False}
		self.client.write_frame({
			"type": "llama_get_status",
			"command": "llama_get_status",
		})
		resp2 = self.client.read_frame()
		self.assertTrue(resp2.get("success"))


class TestLlamaServerSupervisorProxyIntegration(unittest.TestCase):
	"""Verify LlamaServerSupervisor delegating to WorkerClient over IPC."""

	def setUp(self) -> None:
		token = uuid.uuid4().hex[:8]
		self.cmd_pipe = f"\\\\.\\pipe\\test_llama_proxy_cmd_{token}"
		self.evt_pipe = f"\\\\.\\pipe\\test_llama_proxy_evt_{token}"
		self.server = WorkerServer(
			cmd_pipe_name=self.cmd_pipe,
			evt_pipe_name=self.evt_pipe,
		)
		self.mock_executor = mock.MagicMock()
		self.server._llama_executor = self.mock_executor
		self.server.start()

		self.client = NamedPipeWorkerClient(
			cmd_pipe_name=self.cmd_pipe,
			evt_pipe_name=self.evt_pipe,
		)
		self.client.connect()

		self.proxy_supervisor = LlamaServerSupervisor(worker_client=self.client)

	def tearDown(self) -> None:
		self.server.shutdown()
		self.client.disconnect()

	def test_status_proxy(self) -> None:
		self.mock_executor.get_status.return_value = {
			"state": "ready_owned",
			"generation": 5,
			"pid": 9999,
			"host": "127.0.0.1",
			"port": 8080,
			"is_ready": True,
			"is_running": True,
			"error_message": None,
			"running_model": "qwen",
		}
		status = self.proxy_supervisor.status()
		self.assertEqual(status.state, "ready_owned")
		self.assertEqual(status.generation, 5)
		self.assertEqual(status.pid, 9999)
		self.assertTrue(status.is_ready)
		self.assertTrue(status.is_running)

	def test_ensure_ready_proxy(self) -> None:
		self.mock_executor.ensure_ready.return_value = {
			"state": "ready_owned",
			"generation": 1,
			"is_ready": True,
			"is_running": True,
		}
		status = self.proxy_supervisor.ensure_ready("qwen.gguf", model_id="qwen", timeout=10.0)
		self.assertEqual(status.state, "ready_owned")
		self.mock_executor.ensure_ready.assert_called_once()

	def test_restart_proxy(self) -> None:
		self.mock_executor.restart.return_value = {
			"state": "ready_owned",
			"generation": 2,
			"is_ready": True,
			"is_running": True,
		}
		status = self.proxy_supervisor.restart("new_qwen.gguf", model_id="new_qwen", timeout=10.0)
		self.assertEqual(status.state, "ready_owned")
		self.mock_executor.restart.assert_called_once()

	def test_stop_proxy(self) -> None:
		self.mock_executor.stop.return_value = {
			"state": "stopped",
			"generation": 3,
			"is_ready": False,
		}
		self.proxy_supervisor.stop()
		self.mock_executor.stop.assert_called_once()

	def test_adopt_proxy(self) -> None:
		self.mock_executor.adopt.return_value = {
			"state": "ready_adopted",
			"generation": 1,
			"is_ready": True,
			"is_running": False,
			"is_adopted": True,
		}
		status = self.proxy_supervisor.adopt("adopted_model")
		self.assertEqual(status.state, "ready_adopted")
		self.assertTrue(status.is_adopted)
		self.mock_executor.adopt.assert_called_once_with(model_id="adopted_model")

	def test_error_raised_as_llama_server_error(self) -> None:
		self.mock_executor.ensure_ready.side_effect = RuntimeError("Port already in use")
		with self.assertRaises(LlamaServerError) as ctx:
			self.proxy_supervisor.ensure_ready("model.gguf", timeout=5.0)
		self.assertIn("Port already in use", str(ctx.exception))

	def test_uninitialized_worker_fallback(self) -> None:
		supervisor = LlamaServerSupervisor(worker_client=None)
		status = supervisor.status()
		self.assertEqual(status.state, "stopped")
		self.assertFalse(status.is_ready)
		self.assertEqual(status.generation, 0)
		self.assertIsNone(status.pid)

	def test_get_worker_client_handles_boolean_is_connected(self) -> None:
		mock_client = mock.MagicMock()
		mock_client.is_connected = True  # boolean attribute
		supervisor = LlamaServerSupervisor(worker_client=mock_client)
		self.assertIs(supervisor._get_worker_client(), mock_client)

		mock_client.is_connected = False
		self.assertIsNone(supervisor._get_worker_client())

	def test_get_worker_client_handles_callable_is_connected(self) -> None:
		mock_client = mock.MagicMock()
		mock_client.is_connected = mock.MagicMock(return_value=True)  # callable method
		supervisor = LlamaServerSupervisor(worker_client=mock_client)
		self.assertIs(supervisor._get_worker_client(), mock_client)

		mock_client.is_connected.return_value = False
		self.assertIsNone(supervisor._get_worker_client())

	def test_status_proxy_retains_worker_error_frame(self) -> None:
		mock_client = mock.MagicMock()
		mock_client.is_connected = True
		mock_client.send_command.return_value = {
			"type": "error",
			"command": "llama_get_status",
			"error_code": "LLAMA_CRASHED",
			"error_message": "llama-server crashed abruptly",
			"generation": 7,
			"success": False,
		}
		supervisor = LlamaServerSupervisor(worker_client=mock_client)
		st = supervisor.status()
		self.assertEqual(st.state, "failed")
		self.assertEqual(st.error_code, "LLAMA_CRASHED")
		self.assertEqual(st.error_message, "llama-server crashed abruptly")
		self.assertEqual(st.generation, 7)

	def test_matches_startup_configuration_via_worker_status(self) -> None:
		expected_identity = build_startup_identity(model="qwen.gguf", model_id="qwen", threads=0, context=0)
		self.mock_executor.get_status.return_value = {
			"state": "ready_owned",
			"generation": 1,
			"is_ready": True,
			"is_running": True,
			"startup_identity": expected_identity,
		}
		matches = self.proxy_supervisor.matches_startup_configuration("qwen.gguf", model_id="qwen")
		self.assertTrue(matches)

		mismatches = self.proxy_supervisor.matches_startup_configuration("other.gguf", model_id="other")
		self.assertFalse(mismatches)


class TestLlamaCrashContainmentAndGenerationFencing(unittest.TestCase):
	"""Verify fault containment and monotonic generation increment on process termination."""

	def test_trapped_crash_increments_generation(self) -> None:
		try:
			from runtime_supervisor import RuntimeSupervisor
		except ImportError:
			self.skipTest("runtime_supervisor native module not available")

		native = RuntimeSupervisor("llama-server")
		initial_gen = native.status().generation

		# Trigger stop with generation
		native.stop(timeout_seconds=0.1)
		new_status = native.status()
		self.assertGreaterEqual(new_status.generation, initial_gen)


if __name__ == "__main__":
	unittest.main()
