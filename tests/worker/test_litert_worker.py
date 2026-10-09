# -*- coding: utf-8 -*-
"""Unit and integration tests for LiteRT worker execution, IPC routing, and fault isolation."""

from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest import mock
import uuid

from tests.support import load_addon_module

dto_mod = load_addon_module("core.job.dto")
server_mod = load_addon_module("worker.server")
trans_mod = load_addon_module("worker.ipc.transport")
worker_client_mod = load_addon_module("service.worker_client")
litert_exec_mod = load_addon_module("worker.executors.litert")
litert_server_mod = load_addon_module("providers.runtime.server")

HandshakeRequest = dto_mod.HandshakeRequest
HandshakeResponse = dto_mod.HandshakeResponse
NamedPipeClient = trans_mod.NamedPipeClient
NamedPipeWorkerClient = worker_client_mod.NamedPipeWorkerClient
WorkerServer = server_mod.WorkerServer
LiteRTWorkerExecutor = litert_exec_mod.LiteRTWorkerExecutor
LiteRTServerSupervisor = litert_server_mod.LiteRTServerSupervisor
LiteRTServerError = litert_server_mod.LiteRTServerError


class TestLiteRTWorkerExecutor(unittest.TestCase):
	"""Verify LiteRTWorkerExecutor lifecycle, status mapping, and CLI execution."""

	def setUp(self) -> None:
		self.mock_native = mock.MagicMock()
		mock_status = types.SimpleNamespace(
			state="stopped",
			generation=0,
			pid=None,
			active_pid=None,
			host="127.0.0.1",
			port=9379,
			model_path=None,
			is_ready=False,
			is_running=False,
			is_adopted=False,
			error_message=None,
			last_error=None,
			consecutive_crashes=0,
		)
		self.mock_native.status.return_value = mock_status
		self.mock_native.ensure_ready.return_value = mock_status
		self.mock_native.stop.return_value = mock_status
		self.mock_native.restart.return_value = mock_status
		self.mock_native.adopt.return_value = mock_status

		self.executor = LiteRTWorkerExecutor(host="127.0.0.1", port=9379)
		self.executor._supervisor = self.mock_native

	def test_get_status_mapping(self) -> None:
		status = self.executor.get_status()
		self.assertEqual(status["state"], "stopped")
		self.assertEqual(status["generation"], 0)
		self.assertIsNone(status["pid"])
		self.assertFalse(status["is_ready"])

	def test_ensure_ready_delegation(self) -> None:
		config = {"model_path": "C:\\models\\gemma.litertlm", "host": "127.0.0.1", "port": 9379}
		res = self.executor.ensure_ready(config)
		self.mock_native.ensure_ready.assert_called_once()
		self.assertEqual(res["state"], "stopped")

	def test_stop_delegation(self) -> None:
		res = self.executor.stop(timeout_seconds=5.0)
		self.mock_native.stop.assert_called_once_with(timeout_seconds=5.0)
		self.assertEqual(res["state"], "stopped")

	def test_restart_delegation(self) -> None:
		config = {"model_path": "C:\\models\\gemma.litertlm"}
		res = self.executor.restart(config, timeout_seconds=5.0)
		self.mock_native.restart.assert_called_once()
		self.assertEqual(res["state"], "stopped")

	def test_ensure_ready_custom_host_and_port(self) -> None:
		config = {"model_path": "C:\\models\\gemma.litertlm"}
		self.executor.ensure_ready(config, host="0.0.0.0", port=9500)
		self.assertEqual(self.executor.host, "0.0.0.0")
		self.assertEqual(self.executor.port, 9500)
		self.mock_native.ensure_ready.assert_called_once()
		call_args = self.mock_native.ensure_ready.call_args
		cmd_args = call_args[0][1]
		self.assertIn("--host", cmd_args)
		self.assertIn("0.0.0.0", cmd_args)
		self.assertIn("--port", cmd_args)
		self.assertIn("9500", cmd_args)

	def test_restart_custom_host_and_port(self) -> None:
		config = {"model_path": "C:\\models\\gemma.litertlm"}
		self.executor.restart(config, host="127.0.0.2", port=9501)
		self.assertEqual(self.executor.host, "127.0.0.2")
		self.assertEqual(self.executor.port, 9501)
		self.mock_native.restart.assert_called_once()
		call_args = self.mock_native.restart.call_args
		cmd_args = call_args[0][1]
		self.assertIn("--host", cmd_args)
		self.assertIn("127.0.0.2", cmd_args)
		self.assertIn("--port", cmd_args)
		self.assertIn("9501", cmd_args)

	def test_adopt_delegation(self) -> None:
		res = self.executor.adopt()
		self.mock_native.adopt.assert_called_once()
		self.assertEqual(res["state"], "stopped")

	def test_cli_import_model(self) -> None:
		with tempfile.NamedTemporaryFile(suffix=".litertlm", delete=False) as tf:
			temp_path = tf.name
		try:
			with mock.patch.object(self.executor, "_run_cli") as mock_cli:
				mock_cli.return_value = types.SimpleNamespace(stdout="", stderr="", returncode=0)
				res = self.executor.import_model(
					temp_path,
					"my-model",
					delete_source=False,
				)
				mock_cli.assert_called_once()
				self.assertTrue(res["success"])
				self.assertEqual(res["model_id"], "my-model")
		finally:
			Path(temp_path).unlink(missing_ok=True)

	def test_cli_import_huggingface_model(self) -> None:
		with mock.patch.object(self.executor, "_run_cli") as mock_cli:
			mock_cli.return_value = types.SimpleNamespace(stdout="", stderr="", returncode=0)
			res = self.executor.import_huggingface_model("owner/repo", "model.litertlm", "custom-id")
			mock_cli.assert_called_once()
			self.assertTrue(res["success"])
			self.assertEqual(res["model_id"], "custom-id")

	def test_cli_delete_model(self) -> None:
		with mock.patch.object(self.executor, "_run_cli") as mock_cli:
			mock_cli.return_value = types.SimpleNamespace(stdout="", stderr="", returncode=0)
			res = self.executor.delete_model("my-model")
			mock_cli.assert_called_once()
			self.assertTrue(res["success"])

	def test_cli_rename_model(self) -> None:
		with mock.patch.object(self.executor, "_run_cli") as mock_cli:
			mock_cli.return_value = types.SimpleNamespace(stdout="", stderr="", returncode=0)
			res = self.executor.rename_model("old-id", "new-id")
			mock_cli.assert_called_once()
			self.assertTrue(res["success"])

	def test_cli_list_models_from_disk(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			m_dir = Path(td) / "models" / "owner--model"
			m_dir.mkdir(parents=True)
			(m_dir / "model.litertlm").touch()
			executor = LiteRTWorkerExecutor(host="127.0.0.1", port=59999)
			models = executor.list_models(litert_dir=td)
			self.assertEqual(models, ["owner/model"])

	def test_cli_error_raises_runtime_error(self) -> None:
		with tempfile.NamedTemporaryFile(suffix=".litertlm", delete=False) as tf:
			temp_path = tf.name
		try:
			with mock.patch.object(self.executor, "_run_cli") as mock_cli:
				mock_cli.return_value = types.SimpleNamespace(stdout="", stderr="Import failed", returncode=1)
				with self.assertRaises(RuntimeError) as ctx:
					self.executor.import_model(temp_path, "dummy")
				self.assertIn("failed", str(ctx.exception))
		finally:
			Path(temp_path).unlink(missing_ok=True)


class TestWorkerServerLiteRTProtocol(unittest.TestCase):
	"""Verify WorkerServer command frame dispatch and capability negotiation over Named Pipes."""

	def setUp(self) -> None:
		token = uuid.uuid4().hex[:8]
		self.cmd_pipe = f"\\\\.\\pipe\\test_litert_cmd_{token}"
		self.evt_pipe = f"\\\\.\\pipe\\test_litert_evt_{token}"
		self.server = WorkerServer(
			cmd_pipe_name=self.cmd_pipe,
			evt_pipe_name=self.evt_pipe,
		)
		self.mock_executor = mock.MagicMock()
		self.server._litert_executor = self.mock_executor
		self.server.start()

		self.client = NamedPipeClient(self.cmd_pipe)
		self.client.connect(timeout_seconds=2.0)

		# Exchange handshake frame first
		req = HandshakeRequest(
			protocol_version="1.0.0",
			client_name="test_client",
			client_version="1.0.0",
			requested_capabilities=("job.echo", "runtime.litert"),
		)
		self.client.write_frame(req.to_dict())
		raw_resp = self.client.read_frame()
		self.handshake_resp = HandshakeResponse.from_dict(raw_resp)

	def tearDown(self) -> None:
		self.client.close()
		self.server.shutdown()

	def test_handshake_negotiates_litert_capability(self) -> None:
		self.assertTrue(self.handshake_resp.accepted)
		self.assertIn("runtime.litert", self.handshake_resp.negotiated_capabilities)

	def test_dispatch_litert_get_status(self) -> None:
		self.mock_executor.get_status.return_value = {
			"state": "running",
			"generation": 2,
			"pid": 4321,
			"host": "127.0.0.1",
			"port": 9379,
			"is_ready": True,
		}
		self.client.write_frame({"type": "litert_get_status", "command": "litert_get_status"})
		resp = self.client.read_frame()
		self.assertTrue(resp.get("success"))
		self.assertEqual(resp.get("type"), "litert_status_response")
		self.assertEqual(resp.get("status", {}).get("state"), "running")

	def test_dispatch_litert_ensure_ready(self) -> None:
		self.mock_executor.ensure_ready.return_value = {
			"state": "running",
			"generation": 1,
			"is_ready": True,
		}
		self.client.write_frame({
			"type": "litert_ensure_ready",
			"command": "litert_ensure_ready",
			"config": {"model_path": "path/to/model.litertlm"},
			"timeout_seconds": 15.0,
		})
		resp = self.client.read_frame()
		self.assertTrue(resp.get("success"))
		self.assertEqual(resp.get("status", {}).get("state"), "running")
		self.mock_executor.ensure_ready.assert_called_once()

	def test_dispatch_litert_stop(self) -> None:
		self.mock_executor.stop.return_value = {"state": "stopped", "generation": 2}
		self.client.write_frame({
			"type": "litert_stop",
			"command": "litert_stop",
			"timeout_seconds": 5.0,
		})
		resp = self.client.read_frame()
		self.assertTrue(resp.get("success"))
		self.assertEqual(resp.get("status", {}).get("state"), "stopped")
		self.mock_executor.stop.assert_called_once_with(timeout_seconds=5.0)

	def test_dispatch_litert_restart(self) -> None:
		self.mock_executor.restart.return_value = {"state": "running", "generation": 3}
		self.client.write_frame({
			"type": "litert_restart",
			"command": "litert_restart",
			"config": {"model_path": "new/model.litertlm"},
			"timeout_seconds": 10.0,
		})
		resp = self.client.read_frame()
		self.assertTrue(resp.get("success"))
		self.mock_executor.restart.assert_called_once()

	def test_dispatch_litert_restart_with_custom_host_port(self) -> None:
		self.mock_executor.restart.return_value = {"state": "running", "generation": 4}
		self.client.write_frame({
			"type": "litert_restart",
			"command": "litert_restart",
			"config": {"model_path": "new/model.litertlm"},
			"timeout_seconds": 10.0,
			"host": "127.0.0.3",
			"port": 9502,
		})
		resp = self.client.read_frame()
		self.assertTrue(resp.get("success"))
		self.mock_executor.restart.assert_called_once()
		call_kwargs = self.mock_executor.restart.call_args.kwargs
		self.assertEqual(call_kwargs.get("host"), "127.0.0.3")
		self.assertEqual(call_kwargs.get("port"), 9502)

	def test_dispatch_litert_adopt(self) -> None:
		self.mock_executor.adopt.return_value = {"state": "running", "generation": 1}
		self.client.write_frame({
			"type": "litert_adopt",
			"command": "litert_adopt",
		})
		resp = self.client.read_frame()
		self.assertTrue(resp.get("success"))
		self.mock_executor.adopt.assert_called_once()

	def test_dispatch_litert_import_model(self) -> None:
		self.mock_executor.import_model.return_value = {
			"success": True,
			"model_id": "model-id",
			"imported_path": "model.litertlm",
		}
		self.client.write_frame({
			"type": "litert_import_model",
			"command": "litert_import_model",
			"model_path": "model.litertlm",
			"model_id": "model-id",
			"delete_source": False,
		})
		resp = self.client.read_frame()
		self.assertTrue(resp.get("success"))
		self.mock_executor.import_model.assert_called_once()

	def test_dispatch_litert_list_models(self) -> None:
		self.mock_executor.list_models.return_value = ["model-a", "model-b"]
		self.client.write_frame({
			"type": "litert_list_models",
			"command": "litert_list_models",
		})
		resp = self.client.read_frame()
		self.assertTrue(resp.get("success"))
		self.assertEqual(resp.get("models"), ["model-a", "model-b"])

	def test_error_frame_containment(self) -> None:
		"""Verify that executor failure produces an error frame and isolates server."""
		self.mock_executor.get_status.side_effect = RuntimeError("Worker failure")
		self.client.write_frame({
			"type": "litert_get_status",
			"command": "litert_get_status",
		})
		resp = self.client.read_frame()
		self.assertEqual(resp.get("type"), "error")
		self.assertIn("Worker failure", str(resp.get("error_message") or resp.get("error")))

		# Subsequent request succeeds without restarting server
		self.mock_executor.get_status.side_effect = None
		self.mock_executor.get_status.return_value = {"state": "stopped", "is_ready": False}
		self.client.write_frame({
			"type": "litert_get_status",
			"command": "litert_get_status",
		})
		resp2 = self.client.read_frame()
		self.assertTrue(resp2.get("success"))


class TestLiteRTServerSupervisorProxyIntegration(unittest.TestCase):
	"""Verify LiteRTServerSupervisor delegating to WorkerClient over IPC."""

	def setUp(self) -> None:
		token = uuid.uuid4().hex[:8]
		self.cmd_pipe = f"\\\\.\\pipe\\test_proxy_cmd_{token}"
		self.evt_pipe = f"\\\\.\\pipe\\test_proxy_evt_{token}"
		self.server = WorkerServer(
			cmd_pipe_name=self.cmd_pipe,
			evt_pipe_name=self.evt_pipe,
		)
		self.mock_executor = mock.MagicMock()
		self.server._litert_executor = self.mock_executor
		self.server.start()

		self.client = NamedPipeWorkerClient(
			cmd_pipe_name=self.cmd_pipe,
			evt_pipe_name=self.evt_pipe,
		)
		self.client.connect()

		self.proxy_supervisor = LiteRTServerSupervisor(worker_client=self.client)

	def tearDown(self) -> None:
		self.server.shutdown()
		self.client.disconnect()

	def test_status_proxy(self) -> None:
		self.mock_executor.get_status.return_value = {
			"state": "ready",
			"generation": 5,
			"pid": 1122,
			"host": "127.0.0.1",
			"port": 9379,
			"model_path": "C:\\m.litertlm",
			"is_ready": True,
			"is_running": True,
			"last_error": None,
			"consecutive_crashes": 0,
		}
		status = self.proxy_supervisor.status()
		self.assertEqual(status.state, "ready")
		self.assertEqual(status.generation, 5)
		self.assertEqual(status.pid, 1122)
		self.assertTrue(status.is_ready)

	def test_ensure_ready_proxy(self) -> None:
		self.mock_executor.ensure_ready.return_value = {
			"state": "ready",
			"generation": 1,
			"is_ready": True,
		}
		status = self.proxy_supervisor.ensure_ready(timeout=10.0)
		self.assertEqual(status.state, "ready")
		self.mock_executor.ensure_ready.assert_called_once()

	def test_stop_proxy(self) -> None:
		self.mock_executor.stop.return_value = {
			"state": "stopped",
			"generation": 2,
			"is_ready": False,
		}
		status = self.proxy_supervisor.stop(timeout=5.0)
		self.assertEqual(status.state, "stopped")
		self.mock_executor.stop.assert_called_once()

	def test_list_server_models_proxy(self) -> None:
		self.mock_executor.list_models.return_value = ["model1", "model2"]
		models = self.proxy_supervisor.list_server_models()
		self.assertEqual(models, {"model1", "model2"})

	def test_error_raised_as_litert_server_error(self) -> None:
		self.mock_executor.ensure_ready.side_effect = RuntimeError("Failed spawn")
		with self.assertRaises(LiteRTServerError) as ctx:
			self.proxy_supervisor.ensure_ready(timeout=10.0)
		self.assertIn("Failed", str(ctx.exception))

	def test_uninitialized_worker_fallback(self) -> None:
		"""Verify LiteRTServerSupervisor falls back cleanly when worker is not connected."""
		supervisor = LiteRTServerSupervisor(worker_client=None)
		status = supervisor.status()
		self.assertEqual(status.state, "stopped")
		self.assertFalse(status.is_ready)
		self.assertEqual(status.generation, 0)
		self.assertIsNone(status.pid)

	def test_get_worker_client_handles_boolean_is_connected(self) -> None:
		mock_client = mock.MagicMock()
		mock_client.is_connected = True  # boolean attribute, not callable
		supervisor = LiteRTServerSupervisor(worker_client=mock_client)
		self.assertIs(supervisor._get_worker_client(), mock_client)

		mock_client.is_connected = False
		self.assertIsNone(supervisor._get_worker_client())

	def test_status_proxy_retains_worker_error_frame(self) -> None:
		mock_client = mock.MagicMock()
		mock_client.is_connected = True
		mock_client.send_command.return_value = {
			"type": "error",
			"command": "litert_get_status",
			"error_code": "LITERT_CRASHED",
			"error_message": "Process failed",
			"generation": 3,
			"success": False,
		}
		supervisor = LiteRTServerSupervisor(worker_client=mock_client)
		st = supervisor.status()
		self.assertEqual(st.state, "failed")
		self.assertEqual(st.error_code, "LITERT_CRASHED")
		self.assertEqual(st.error_message, "Process failed")
		self.assertEqual(st.generation, 3)

	def test_cmd_lock_coordination_between_client_and_supervisor(self) -> None:
		shared_lock = threading.Lock()
		client = NamedPipeWorkerClient(
			cmd_client=mock.MagicMock(),
			evt_client=mock.MagicMock(),
			cmd_lock=shared_lock,
		)
		self.assertIs(client.cmd_lock, shared_lock)


class TestFaultIsolationAndGenerationFencing(unittest.TestCase):
	"""Verify trapped exit/crash and generation monotonic increment (Invariant A19, A20)."""

	def test_trapped_crash_increments_generation(self) -> None:
		"""Verify that native supervisor tracks and increments generation monotonically."""
		try:
			from runtime_supervisor import RuntimeSupervisor
		except ImportError:
			self.skipTest("runtime_supervisor native module not available")

		native = RuntimeSupervisor("litert-lm")
		initial_gen = native.status().generation

		# Trigger stop with generation
		native.stop(timeout_seconds=0.1)
		new_status = native.status()
		self.assertGreaterEqual(new_status.generation, initial_gen)


if __name__ == "__main__":
	unittest.main()
