# -*- coding: utf-8 -*-
"""Adversarial stress and edge-case empirical challenge tests for Slice 7 (llama.cpp Worker).

Validates:
1. Custom Host & Port Propagation across WorkerServer, LlamaWorkerExecutor, and LlamaServerSupervisor.
2. Router Preset Configuration (llama_configure_preset): valid models, empty models, missing defaults, malformed records.
3. Worker Error Response Preservation: ensuring state="failed", error_code, and error_message are preserved and never swallowed into state="stopped".
4. High-concurrency stress, broken pipe recovery, and process crash containment.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import threading
import time
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
llama_mgr_mod = load_addon_module("providers.llama_manager")
llama_models_mod = load_addon_module("providers.runtime.llama_models")

HandshakeRequest = dto_mod.HandshakeRequest
HandshakeResponse = dto_mod.HandshakeResponse
NamedPipeClient = trans_mod.NamedPipeClient
NamedPipeServer = trans_mod.NamedPipeServer
PipeDisconnectedError = trans_mod.PipeDisconnectedError
NamedPipeWorkerClient = worker_client_mod.NamedPipeWorkerClient
WorkerServer = server_mod.WorkerServer
LlamaWorkerExecutor = llama_exec_mod.LlamaWorkerExecutor
build_llama_server_args = llama_exec_mod.build_llama_server_args
build_startup_identity = llama_exec_mod.build_startup_identity
merge_models_preset = llama_exec_mod.merge_models_preset
build_models_preset = llama_exec_mod.build_models_preset
LlamaServerSupervisor = llama_server_mod.LlamaServerSupervisor
LlamaServerError = llama_server_mod.LlamaServerError
LlamaCppModelManager = llama_mgr_mod.LlamaCppModelManager
LlamaModelRecord = llama_models_mod.LlamaModelRecord


class TestCustomHostAndPortPropagation(unittest.TestCase):
	"""Adversarially challenge custom host & port propagation (Dead End M1 Iter 1 regression prevention)."""

	def setUp(self) -> None:
		token = uuid.uuid4().hex[:8]
		self.cmd_pipe = f"\\\\.\\pipe\\test_llama_hostport_cmd_{token}"
		self.evt_pipe = f"\\\\.\\pipe\\test_llama_hostport_evt_{token}"
		self.server = WorkerServer(
			cmd_pipe_name=self.cmd_pipe,
			evt_pipe_name=self.evt_pipe,
		)
		self.mock_executor = mock.MagicMock()
		self.server._llama_executor = self.mock_executor
		self.server.start()

		self.client = NamedPipeClient(self.cmd_pipe)
		self.client.connect(timeout_seconds=2.0)

		# Handshake
		req = HandshakeRequest(
			protocol_version="1.0.0",
			client_name="challenger_hostport",
			client_version="1.0.0",
			requested_capabilities=("job.echo", "runtime.llama"),
		)
		self.client.write_frame(req.to_dict())
		raw_resp = self.client.read_frame()
		self.assertTrue(raw_resp.get("accepted"))

	def tearDown(self) -> None:
		self.client.close()
		self.server.shutdown()

	def test_worker_server_forwards_custom_host_and_port_on_ensure_ready(self) -> None:
		"""Verify WorkerServer decodes custom host and port and passes them to LlamaWorkerExecutor."""
		self.mock_executor.ensure_ready.return_value = {
			"state": "ready_owned",
			"generation": 1,
			"is_ready": True,
		}
		self.client.write_frame({
			"type": "llama_ensure_ready",
			"command": "llama_ensure_ready",
			"model": "qwen.gguf",
			"host": "0.0.0.0",
			"port": 8088,
			"timeout_seconds": 30.0,
		})
		resp = self.client.read_frame()
		self.assertTrue(resp.get("success"))
		self.mock_executor.ensure_ready.assert_called_once()
		call_kwargs = self.mock_executor.ensure_ready.call_args.kwargs
		self.assertEqual(call_kwargs.get("host"), "0.0.0.0")
		self.assertEqual(call_kwargs.get("port"), 8088)

	def test_worker_server_forwards_custom_host_and_port_on_restart(self) -> None:
		"""Verify WorkerServer forwards custom host and port on restart command."""
		self.mock_executor.restart.return_value = {
			"state": "ready_owned",
			"generation": 2,
			"is_ready": True,
		}
		self.client.write_frame({
			"type": "llama_restart",
			"command": "llama_restart",
			"model": "qwen.gguf",
			"host": "127.0.0.2",
			"port": 8099,
			"timeout_seconds": 25.0,
		})
		resp = self.client.read_frame()
		self.assertTrue(resp.get("success"))
		self.mock_executor.restart.assert_called_once()
		call_kwargs = self.mock_executor.restart.call_args.kwargs
		self.assertEqual(call_kwargs.get("host"), "127.0.0.2")
		self.assertEqual(call_kwargs.get("port"), 8099)

	def test_worker_server_coerces_string_port_to_integer(self) -> None:
		"""WorkerServer coerces string port ('8088') to int (8088)."""
		self.mock_executor.ensure_ready.return_value = {"state": "ready", "is_ready": True}
		self.client.write_frame({
			"type": "llama_ensure_ready",
			"command": "llama_ensure_ready",
			"model": "qwen.gguf",
			"host": "127.0.0.1",
			"port": "8088",
		})
		resp = self.client.read_frame()
		self.assertTrue(resp.get("success"))
		call_kwargs = self.mock_executor.ensure_ready.call_args.kwargs
		self.assertIsInstance(call_kwargs.get("port"), int)
		self.assertEqual(call_kwargs.get("port"), 8088)

	def test_worker_server_handles_invalid_port_string_gracefully(self) -> None:
		"""WorkerServer rejects non-integer port string with error frame without crashing."""
		self.client.write_frame({
			"type": "llama_ensure_ready",
			"command": "llama_ensure_ready",
			"model": "qwen.gguf",
			"port": "invalid_port_not_number",
		})
		resp = self.client.read_frame()
		self.assertEqual(resp.get("type"), "error")
		self.assertEqual(resp.get("error_code"), "LLAMA_START_FAILED")
		self.assertFalse(resp.get("success"))

		# Follow-up command still works
		self.mock_executor.get_status.return_value = {"state": "stopped", "is_ready": False}
		self.client.write_frame({"type": "llama_get_status", "command": "llama_get_status"})
		resp2 = self.client.read_frame()
		self.assertTrue(resp2.get("success"))

	def test_llama_worker_executor_updates_host_port_and_args(self) -> None:
		"""Verify LlamaWorkerExecutor modifies self.host and self.port and generates CLI flags."""
		mock_native = mock.MagicMock()
		mock_native.ensure_ready.return_value = types.SimpleNamespace(
			state="ready_owned",
			is_ready=True,
			is_running=True,
			is_adopted=False,
			pid=1234,
			generation=1,
			error_message=None,
			startup_identity=None,
			running_model="qwen",
			base_url="http://0.0.0.0:8088",
		)
		executor = LlamaWorkerExecutor(host="127.0.0.1", port=8080, supervisor=mock_native)
		self.assertEqual(executor.host, "127.0.0.1")
		self.assertEqual(executor.port, 8080)

		res = executor.ensure_ready(model="C:\\models\\qwen.gguf", host="0.0.0.0", port=8088)
		self.assertEqual(executor.host, "0.0.0.0")
		self.assertEqual(executor.port, 8088)
		self.assertEqual(res["base_url"], "http://0.0.0.0:8088")

		call_args = mock_native.ensure_ready.call_args[0][1]
		self.assertIn("--host", call_args)
		self.assertIn("0.0.0.0", call_args)
		self.assertIn("--port", call_args)
		self.assertIn("8088", call_args)

	def test_llama_worker_executor_restart_updates_host_and_port(self) -> None:
		"""Verify restart method updates host and port on executor."""
		mock_native = mock.MagicMock()
		mock_native.restart.return_value = types.SimpleNamespace(
			state="ready_owned",
			is_ready=True,
			is_running=True,
			is_adopted=False,
			pid=5678,
			generation=2,
			error_message=None,
			startup_identity=None,
			running_model="qwen",
			base_url="http://127.0.0.5:8095",
		)
		executor = LlamaWorkerExecutor(host="127.0.0.1", port=8080, supervisor=mock_native)
		res = executor.restart(model="C:\\models\\qwen.gguf", host="127.0.0.5", port=8095)
		self.assertEqual(executor.host, "127.0.0.5")
		self.assertEqual(executor.port, 8095)
		self.assertEqual(res["base_url"], "http://127.0.0.5:8095")

		call_args = mock_native.restart.call_args[0][1]
		self.assertIn("--host", call_args)
		self.assertIn("127.0.0.5", call_args)
		self.assertIn("--port", call_args)
		self.assertIn("8095", call_args)

	def test_executor_get_status_reports_custom_host_and_port(self) -> None:
		"""LlamaWorkerExecutor get_status reports base_url containing configured host:port."""
		executor = LlamaWorkerExecutor(host="0.0.0.0", port=8088)
		status = executor.get_status()
		self.assertEqual(status["base_url"], "http://0.0.0.0:8088")

	def test_executor_handles_ipv6_host_bracket_formatting(self) -> None:
		"""LlamaWorkerExecutor get_status wraps IPv6 addresses in brackets."""
		executor = LlamaWorkerExecutor(host="::1", port=8088, supervisor=None)
		status = executor.get_status()
		self.assertEqual(status["base_url"], "http://[::1]:8088")


class TestRouterPresetConfigurationEmpirical(unittest.TestCase):
	"""Adversarially challenge router preset configuration mechanics and validation."""

	def setUp(self) -> None:
		self.executor = LlamaWorkerExecutor()

	def test_configure_preset_valid_model_list_atomic_write_and_sha256(self) -> None:
		"""Validate atomic write, INI sections, and SHA256 calculation with HF and local models."""
		with tempfile.TemporaryDirectory() as td:
			target_ini = Path(td) / "preset_dir" / "models.ini"
			models = [
				{
					"model_id": "hf_model",
					"source": "hf://unsloth/Qwen3-8B-GGUF",
					"kind": "hugging_face",
					"variant": "UD-Q4_K_XL",
				},
				{
					"model_id": "local_gguf",
					"source": str(Path(td) / "model.gguf"),
					"kind": "local_file",
					"local_path": str(Path(td) / "model.gguf"),
				},
			]
			res = self.executor.configure_preset(
				models=models,
				default_model="hf_model",
				preset_path=target_ini,
			)
			self.assertTrue(res["success"])
			self.assertEqual(res["preset_path"], str(target_ini))
			self.assertTrue(target_ini.is_file())

			content = target_ini.read_text(encoding="utf-8")
			self.assertIn("version = 1", content)
			self.assertIn("[hf_model]", content)
			self.assertIn("hf-repo = unsloth/Qwen3-8B-GGUF:UD-Q4_K_XL", content)
			self.assertIn("[local_gguf]", content)

			expected_hash = hashlib.sha256(target_ini.read_bytes()).hexdigest()
			self.assertEqual(res["sha256"], expected_hash)

	def test_configure_preset_empty_model_list(self) -> None:
		"""Empty model list must produce a valid minimal preset with version=1 and valid hash."""
		with tempfile.TemporaryDirectory() as td:
			target_ini = Path(td) / "empty_models.ini"
			res = self.executor.configure_preset(
				models=[],
				preset_path=target_ini,
			)
			self.assertTrue(res["success"])
			self.assertTrue(target_ini.is_file())

			content = target_ini.read_text(encoding="utf-8")
			self.assertIn("version = 1", content)
			expected_hash = hashlib.sha256(target_ini.read_bytes()).hexdigest()
			self.assertEqual(res["sha256"], expected_hash)

	def test_configure_preset_missing_default_model(self) -> None:
		"""Missing default_model does not fail; preserves original order gracefully."""
		with tempfile.TemporaryDirectory() as td:
			target_ini = Path(td) / "models.ini"
			models = [
				{"model_id": "m1", "source": "repo/1", "kind": "hugging_face"},
				{"model_id": "m2", "source": "repo/2", "kind": "hugging_face"},
			]
			res = self.executor.configure_preset(
				models=models,
				default_model="ghost_model_nonexistent",
				preset_path=target_ini,
			)
			self.assertTrue(res["success"])
			content = target_ini.read_text(encoding="utf-8")
			self.assertIn("[m1]", content)
			self.assertIn("[m2]", content)
			# Order maintained
			self.assertLess(content.find("[m1]"), content.find("[m2]"))

	def test_configure_preset_malformed_records(self) -> None:
		"""List containing None, non-dict, missing model_id, or empty string is filtered out gracefully."""
		with tempfile.TemporaryDirectory() as td:
			target_ini = Path(td) / "models.ini"
			models = [
				None,
				"not_a_dict",
				42,
				{"foo": "bar"},  # missing model_id
				{"model_id": ""},  # empty model_id
				{"model_id": "   "},  # whitespace model_id
				{"model_id": "valid_one", "source": "repo/valid", "kind": "hugging_face"},
			]
			res = self.executor.configure_preset(
				models=models,
				preset_path=target_ini,
			)
			self.assertTrue(res["success"])
			content = target_ini.read_text(encoding="utf-8")
			self.assertIn("[valid_one]", content)
			self.assertNotIn("not_a_dict", content)
			self.assertNotIn("foo", content)

	def test_configure_preset_ipc_missing_models_key(self) -> None:
		"""IPC command frame missing 'models' defaults to empty list and succeeds."""
		token = uuid.uuid4().hex[:8]
		cmd_pipe = f"\\\\.\\pipe\\test_llama_preset_ipc_{token}"
		evt_pipe = f"\\\\.\\pipe\\test_llama_preset_ipcevt_{token}"
		server = WorkerServer(cmd_pipe_name=cmd_pipe, evt_pipe_name=evt_pipe)
		server.start()

		client = NamedPipeClient(cmd_pipe)
		client.connect(timeout_seconds=2.0)

		# Handshake
		req = HandshakeRequest(
			protocol_version="1.0.0",
			client_name="test_preset_client",
			client_version="1.0.0",
			requested_capabilities=("job.echo", "runtime.llama"),
		)
		client.write_frame(req.to_dict())
		client.read_frame()

		with tempfile.TemporaryDirectory() as td:
			preset_file = Path(td) / "ipc_models.ini"
			client.write_frame({
				"type": "llama_configure_preset",
				"command": "llama_configure_preset",
				"preset_path": str(preset_file),
				# 'models' key omitted
			})
			resp = client.read_frame()
			self.assertTrue(resp.get("success"))
			self.assertEqual(resp.get("type"), "llama_configure_preset_response")
			self.assertTrue(preset_file.is_file())
			self.assertIn("version = 1", preset_file.read_text(encoding="utf-8"))

		client.close()
		server.shutdown()

	def test_configure_preset_ipc_invalid_models_type_returns_error_frame(self) -> None:
		"""IPC command frame with models=None or non-iterable returns LLAMA_PRESET_FAILED error frame."""
		token = uuid.uuid4().hex[:8]
		cmd_pipe = f"\\\\.\\pipe\\test_llama_preset_err_{token}"
		evt_pipe = f"\\\\.\\pipe\\test_llama_preset_errevt_{token}"
		server = WorkerServer(cmd_pipe_name=cmd_pipe, evt_pipe_name=evt_pipe)
		server.start()

		client = NamedPipeClient(cmd_pipe)
		client.connect(timeout_seconds=2.0)

		# Handshake
		req = HandshakeRequest(
			protocol_version="1.0.0",
			client_name="test_preset_err_client",
			client_version="1.0.0",
			requested_capabilities=("job.echo", "runtime.llama"),
		)
		client.write_frame(req.to_dict())
		client.read_frame()

		client.write_frame({
			"type": "llama_configure_preset",
			"command": "llama_configure_preset",
			"models": None,  # Not iterable
		})
		resp = client.read_frame()
		self.assertEqual(resp.get("type"), "error")
		self.assertEqual(resp.get("error_code"), "LLAMA_PRESET_FAILED")
		self.assertFalse(resp.get("success"))

		client.close()
		server.shutdown()

	def test_build_models_preset_rejects_section_injection(self) -> None:
		"""build_models_preset filters out model_ids containing brackets or newlines."""
		models = [
			{"model_id": "malicious\n[injected]\ncommand = 1", "source": "repo/bad"},
			{"model_id": "[bracket_injection]", "source": "repo/bad"},
			{"model_id": "clean_model", "source": "repo/clean", "kind": "hugging_face"},
		]
		output = build_models_preset(models)
		self.assertNotIn("injected", output)
		self.assertNotIn("bracket_injection", output)
		self.assertIn("[clean_model]", output)


class TestWorkerErrorResponsePreservation(unittest.TestCase):
	"""Adversarially challenge error response preservation across WorkerServer, LlamaServerSupervisor, and LlamaCppModelManager."""

	def test_status_proxy_preserves_error_frame_as_failed_state(self) -> None:
		"""When worker returns an error frame, status() preserves state='failed' and error details."""
		mock_client = mock.MagicMock()
		mock_client.is_connected = True
		mock_client.send_command.return_value = {
			"type": "error",
			"command": "llama_get_status",
			"error_code": "LLAMA_CRASHED",
			"error_message": "llama-server process died unexpectedly with code 139",
			"generation": 5,
			"success": False,
		}
		supervisor = LlamaServerSupervisor(worker_client=mock_client)
		st = supervisor.status()

		self.assertEqual(st.state, "failed")
		self.assertEqual(st.error_code, "LLAMA_CRASHED")
		self.assertEqual(st.error_message, "llama-server process died unexpectedly with code 139")
		self.assertEqual(st.generation, 5)
		self.assertFalse(st.is_ready)
		self.assertFalse(st.is_running)

	def test_status_proxy_preserves_failed_status_dict(self) -> None:
		"""When worker status dict reports state='failed', proxy preserves state and message."""
		mock_client = mock.MagicMock()
		mock_client.is_connected = True
		mock_client.send_command.return_value = {
			"type": "llama_status_response",
			"command": "llama_get_status",
			"success": True,
			"status": {
				"state": "failed",
				"is_ready": False,
				"is_running": False,
				"is_adopted": False,
				"pid": None,
				"generation": 8,
				"error_message": "Port 8080 already bound by another process",
				"base_url": "http://127.0.0.1:8080",
			},
		}
		supervisor = LlamaServerSupervisor(worker_client=mock_client)
		st = supervisor.status()

		self.assertEqual(st.state, "failed")
		self.assertEqual(st.error_message, "Port 8080 already bound by another process")
		self.assertEqual(st.generation, 8)
		self.assertFalse(st.is_ready)

	def test_ensure_ready_proxy_raises_llama_server_error_preserving_message(self) -> None:
		"""ensure_ready proxy raises LlamaServerError with verbatim worker error message."""
		mock_client = mock.MagicMock()
		mock_client.is_connected = True
		mock_client.send_command.return_value = {
			"type": "error",
			"command": "llama_ensure_ready",
			"error_code": "LLAMA_START_FAILED",
			"error_message": "CUDA out of memory during context allocation",
			"success": False,
		}
		supervisor = LlamaServerSupervisor(worker_client=mock_client)
		with self.assertRaises(LlamaServerError) as ctx:
			supervisor.ensure_ready("model.gguf", timeout=5.0)

		self.assertIn("CUDA out of memory during context allocation", str(ctx.exception))

	def test_restart_proxy_raises_llama_server_error_preserving_message(self) -> None:
		"""restart proxy raises LlamaServerError with verbatim worker error message."""
		mock_client = mock.MagicMock()
		mock_client.is_connected = True
		mock_client.send_command.return_value = {
			"type": "error",
			"command": "llama_restart",
			"error_code": "LLAMA_RESTART_FAILED",
			"error_message": "Failed to kill existing llama-server process handle",
			"success": False,
		}
		supervisor = LlamaServerSupervisor(worker_client=mock_client)
		with self.assertRaises(LlamaServerError) as ctx:
			supervisor.restart("model.gguf", timeout=5.0)

		self.assertIn("Failed to kill existing llama-server process handle", str(ctx.exception))

	def test_adopt_proxy_raises_llama_server_error_on_failure(self) -> None:
		"""adopt proxy raises LlamaServerError on error frame."""
		mock_client = mock.MagicMock()
		mock_client.is_connected = True
		mock_client.send_command.return_value = {
			"type": "error",
			"command": "llama_adopt",
			"error_code": "LLAMA_ADOPT_FAILED",
			"error_message": "No healthy server responded on port 8080",
			"success": False,
		}
		supervisor = LlamaServerSupervisor(worker_client=mock_client)
		with self.assertRaises(LlamaServerError) as ctx:
			supervisor.adopt("adopted_m")

		self.assertIn("No healthy server responded on port 8080", str(ctx.exception))

	def test_model_manager_ensure_running_propagates_llama_server_error(self) -> None:
		"""LlamaCppModelManager.ensure_running propagates LlamaServerError without swallowing."""
		mock_client = mock.MagicMock()
		mock_client.is_connected = True
		mock_client.send_command.return_value = {
			"type": "error",
			"command": "llama_ensure_ready",
			"error_code": "LLAMA_START_FAILED",
			"error_message": "Insufficient VRAM to load GGUF tensors",
			"success": False,
		}
		mgr = LlamaCppModelManager(worker_client=mock_client)
		rec = LlamaModelRecord(model_id="heavy_qwen", source="heavy.gguf", kind="local_file")

		with self.assertRaises(LlamaServerError) as ctx:
			mgr.ensure_running(rec)

		self.assertIn("Insufficient VRAM to load GGUF tensors", str(ctx.exception))

	def test_unhandled_executor_exception_in_worker_returns_structured_error_frame(self) -> None:
		"""WorkerServer catches unexpected exception in LlamaWorkerExecutor and returns error frame."""
		token = uuid.uuid4().hex[:8]
		cmd_pipe = f"\\\\.\\pipe\\test_llama_unhandled_err_{token}"
		evt_pipe = f"\\\\.\\pipe\\test_llama_unhandled_errevt_{token}"
		server = WorkerServer(cmd_pipe_name=cmd_pipe, evt_pipe_name=evt_pipe)
		mock_executor = mock.MagicMock()
		mock_executor.ensure_ready.side_effect = RuntimeError("Fatal hardware I/O error")
		server._llama_executor = mock_executor
		server.start()

		client = NamedPipeClient(cmd_pipe)
		client.connect(timeout_seconds=2.0)

		# Handshake
		req = HandshakeRequest(
			protocol_version="1.0.0",
			client_name="test_unhandled_client",
			client_version="1.0.0",
			requested_capabilities=("job.echo", "runtime.llama"),
		)
		client.write_frame(req.to_dict())
		client.read_frame()

		client.write_frame({
			"type": "llama_ensure_ready",
			"command": "llama_ensure_ready",
			"model": "model.gguf",
		})
		resp = client.read_frame()
		self.assertEqual(resp.get("type"), "error")
		self.assertEqual(resp.get("error_code"), "LLAMA_START_FAILED")
		self.assertIn("Fatal hardware I/O error", str(resp.get("error_message")))

		# Subsequent request functions normally
		mock_executor.get_status.side_effect = None
		mock_executor.get_status.return_value = {"state": "stopped", "is_ready": False}
		client.write_frame({"type": "llama_get_status", "command": "llama_get_status"})
		resp2 = client.read_frame()
		self.assertTrue(resp2.get("success"))

		client.close()
		server.shutdown()


class TestLlamaWorkerStressAndFaultIsolation(unittest.TestCase):
	"""High-throughput concurrency stress, broken pipe recovery, and fault isolation."""

	def setUp(self) -> None:
		token = uuid.uuid4().hex[:8]
		self.cmd_pipe = f"\\\\.\\pipe\\chal_llama_stress_cmd_{token}"
		self.evt_pipe = f"\\\\.\\pipe\\chal_llama_stress_evt_{token}"
		self.server = WorkerServer(
			cmd_pipe_name=self.cmd_pipe,
			evt_pipe_name=self.evt_pipe,
		)
		self.mock_executor = mock.MagicMock()
		self.mock_executor.get_status.return_value = {
			"state": "ready_owned",
			"generation": 10,
			"pid": 5555,
			"is_ready": True,
			"is_running": True,
		}
		self.mock_executor.list_models.return_value = [{"id": "m1"}, {"id": "m2"}]
		self.mock_executor.adopt.return_value = {"state": "ready_adopted", "generation": 11}
		self.server._llama_executor = self.mock_executor
		self.server.start()

		self.client = NamedPipeWorkerClient(
			cmd_pipe_name=self.cmd_pipe,
			evt_pipe_name=self.evt_pipe,
		)
		self.client.connect()

	def tearDown(self) -> None:
		self.client.disconnect()
		self.server.shutdown()

	def test_rapid_sequential_status_queries(self) -> None:
		"""Send 50 rapid sequential llama_get_status commands."""
		start = time.perf_counter()
		for i in range(50):
			resp = self.client.send_command({"type": "llama_get_status", "command": "llama_get_status"})
			self.assertTrue(resp.get("success"))
			self.assertEqual(resp.get("status", {}).get("generation"), 10)
		elapsed = time.perf_counter() - start
		self.assertLess(elapsed, 2.0)

	def test_concurrent_threads_calling_send_command(self) -> None:
		"""Multi-threaded stress test: 8 threads concurrently sending 15 commands each."""
		num_threads = 8
		cmds_per_thread = 15
		errors: list[Exception] = []

		def worker_thread(tid: int) -> None:
			for i in range(cmds_per_thread):
				try:
					if i % 3 == 0:
						resp = self.client.send_command({
							"type": "llama_get_status",
							"command": "llama_get_status",
							"thread_id": tid,
						})
						assert resp.get("success") is True
					elif i % 3 == 1:
						resp = self.client.send_command({
							"type": "llama_list_models",
							"command": "llama_list_models",
							"thread_id": tid,
						})
						assert resp.get("success") is True
						assert len(resp.get("models", [])) == 2
					else:
						resp = self.client.send_command({
							"type": "llama_adopt",
							"command": "llama_adopt",
							"thread_id": tid,
						})
						assert resp.get("success") is True
				except Exception as exc:
					errors.append(exc)

		threads = [threading.Thread(target=worker_thread, args=(i,)) for i in range(num_threads)]
		for t in threads:
			t.start()
		for t in threads:
			t.join(timeout=10.0)

		self.assertEqual(len(errors), 0, f"Errors in concurrent send_command: {errors}")

	def test_broken_pipe_raises_promptly(self) -> None:
		"""Killing worker causes send_command to raise broken pipe error promptly (< 0.5s)."""
		token = uuid.uuid4().hex[:8]
		cmd_pipe = f"\\\\.\\pipe\\chal_llama_broken_cmd_{token}"
		evt_pipe = f"\\\\.\\pipe\\chal_llama_broken_evt_{token}"
		server = WorkerServer(cmd_pipe_name=cmd_pipe, evt_pipe_name=evt_pipe)
		server.start()

		client = NamedPipeWorkerClient(cmd_pipe_name=cmd_pipe, evt_pipe_name=evt_pipe)
		client.connect()

		# Kill server abruptly
		server.shutdown()

		start = time.perf_counter()
		with self.assertRaises((PipeDisconnectedError, OSError, RuntimeError)):
			client.send_command({"type": "llama_get_status"}, timeout=1.0)
		elapsed = time.perf_counter() - start
		self.assertLess(elapsed, 0.5)

		client.disconnect()

	def test_supervisor_status_during_broken_pipe_never_hangs(self) -> None:
		"""LlamaServerSupervisor.status() completes in < 50ms during worker broken pipe."""
		token = uuid.uuid4().hex[:8]
		cmd_pipe = f"\\\\.\\pipe\\chal_llama_status_break_cmd_{token}"
		evt_pipe = f"\\\\.\\pipe\\chal_llama_status_break_evt_{token}"

		server = WorkerServer(cmd_pipe_name=cmd_pipe, evt_pipe_name=evt_pipe)
		server.start()

		client = NamedPipeWorkerClient(cmd_pipe_name=cmd_pipe, evt_pipe_name=evt_pipe)
		client.connect()
		supervisor = LlamaServerSupervisor(worker_client=client)

		server.shutdown()

		for _ in range(5):
			t0 = time.perf_counter()
			st = supervisor.status()
			elapsed = time.perf_counter() - t0
			self.assertEqual(st.state, "stopped")
			self.assertLess(elapsed, 0.05)

		client.disconnect()


if __name__ == "__main__":
	unittest.main()
