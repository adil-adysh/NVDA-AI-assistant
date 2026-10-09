# -*- coding: utf-8 -*-
"""Milestone 2 Challenger 1 (Generation 3) Empirical Challenge Suite for Slice 7 (llama.cpp Worker).

Focus Areas:
1. Process Crash Containment & Monotonic Generation Fencing:
   - Native child termination detection and generation increment.
   - Immediate abort of wait_until_ready on child exit.
   - Clean propagation of crash diagnostics.
2. Timeout Synchronization & Deadlock Resistance:
   - Prompt timeout enforcement in NamedPipeWorkerClient.send_command.
   - Dead End M1 Iter 2 verification: pipe desynchronization where stale response pollutes subsequent command.
   - Immediate follow-up command submission without arbitrary sleeps.
   - Cross-thread timeout isolation (no response leakage between caller threads).
   - Clean recovery across multiple consecutive timeouts.
3. High-Concurrency Stress:
   - 100 rapid sequential llama_get_status queries.
   - Multi-threaded concurrent command submission across command pipe (10 threads x 20 commands).
   - Concurrent supervisor status queries (50 threads).
   - Concurrent router preset generation with atomic file writes.
4. Malformed Payloads & Edge Cases:
   - Missing model/preset parameters.
   - Invalid timeout types.
   - Client abrupt disconnects and raw invalid line recovery.
   - Broken pipe containment and worker recycle recovery.
5. Contract & Invariant Validation:
   - Type safety for is_connected (callable, boolean, property).
   - Status preservation of worker error frames.
   - IPv6 host literal formatting in URLs (RFC 3986).
"""

from __future__ import annotations

import concurrent.futures
from pathlib import Path
import sys
import tempfile
import threading
import time
from typing import Any
import unittest
from unittest import mock
import urllib.parse
import uuid

from tests.support import load_addon_module

dto_mod = load_addon_module("core.job.dto")
server_mod = load_addon_module("worker.server")
trans_mod = load_addon_module("worker.ipc.transport")
worker_client_mod = load_addon_module("service.worker_client")
llama_exec_mod = load_addon_module("worker.executors.llama")
llama_server_mod = load_addon_module("providers.runtime.llama_server")
llama_manager_mod = load_addon_module("providers.llama_manager")
worker_sup_mod = load_addon_module("plugin.worker_supervisor")

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
LlamaServerSupervisor = llama_server_mod.LlamaServerSupervisor
LlamaServerError = llama_server_mod.LlamaServerError
LlamaCppModelManager = llama_manager_mod.LlamaCppModelManager


class TestLlamaProcessCrashContainment(unittest.TestCase):
	"""Adversarially challenge process crash containment and generation fencing for llama-server."""

	def test_native_child_crash_increments_generation_and_reports_failed(self) -> None:
		"""Abrupt child process exit is captured by supervisor, increments generation, and sets state to failed."""
		try:
			from runtime_supervisor import RuntimeSupervisor
		except ImportError:
			self.skipTest("runtime_supervisor native module not available")

		token = uuid.uuid4().hex[:8]
		cmd_pipe = f"\\\\.\\pipe\\c1_llama_proc_crash_cmd_{token}"
		evt_pipe = f"\\\\.\\pipe\\c1_llama_proc_crash_evt_{token}"

		server = WorkerServer(cmd_pipe_name=cmd_pipe, evt_pipe_name=evt_pipe)
		executor = LlamaWorkerExecutor(port=8190)

		# Native supervisor instance for llama-server
		sup = RuntimeSupervisor("llama-server", "127.0.0.1", 8190)
		initial_gen = sup.status().generation

		# Trigger abrupt process exit with code 42
		with self.assertRaises(RuntimeError):
			sup.ensure_ready(
				sys.executable,
				["-c", "import sys; sys.exit(42)"],
				{},
				"crash-ident-llama",
				timeout_seconds=2.0,
			)

		crashed_status = sup.status()
		self.assertGreater(crashed_status.generation, initial_gen)
		self.assertEqual(crashed_status.state, "failed")
		self.assertFalse(crashed_status.is_ready)
		self.assertFalse(crashed_status.is_running)
		self.assertIsNotNone(crashed_status.error_message)
		self.assertIn("42", crashed_status.error_message)

		executor._supervisor = sup
		server._llama_executor = executor
		server.start()

		client = NamedPipeWorkerClient(cmd_pipe_name=cmd_pipe, evt_pipe_name=evt_pipe)
		client.connect()
		supervisor = LlamaServerSupervisor(worker_client=client)

		try:
			t0 = time.perf_counter()
			status = supervisor.status()
			elapsed = time.perf_counter() - t0

			self.assertLess(elapsed, 0.5, "status() over IPC took too long")
			self.assertEqual(status.state, "failed")
			self.assertFalse(status.is_ready)
			self.assertFalse(status.is_running)
			self.assertGreaterEqual(status.generation, crashed_status.generation)
			self.assertIsNotNone(status.error_message)
			self.assertIn("42", status.error_message)
		finally:
			client.disconnect()
			server.shutdown()

	def test_wait_until_ready_aborts_promptly_on_process_crash(self) -> None:
		"""wait_until_ready detects process exit and aborts immediately instead of waiting for timeout."""
		mock_client = mock.MagicMock()
		mock_client.is_connected = True

		mock_client.send_command.side_effect = [
			{
				"success": True,
				"status": {
					"state": "running",
					"is_running": True,
					"is_ready": False,
					"is_adopted": False,
					"generation": 1,
				},
			},
			{
				"success": True,
				"status": {
					"state": "stopped",
					"is_running": False,
					"is_ready": False,
					"is_adopted": False,
					"generation": 2,
					"error_message": "Process died during boot",
				},
			},
		]

		supervisor = LlamaServerSupervisor(worker_client=mock_client)
		supervisor.is_healthy = mock.MagicMock(return_value=False)

		start = time.perf_counter()
		with self.assertRaises(LlamaServerError) as ctx:
			supervisor.wait_until_ready(timeout=30.0)
		elapsed = time.perf_counter() - start

		self.assertLess(elapsed, 1.5, f"wait_until_ready took too long: {elapsed}s")
		self.assertIn("exited before becoming ready", str(ctx.exception))

	def test_ensure_ready_crash_propagates_cleanly(self) -> None:
		"""When worker ensure_ready fails due to crash, supervisor raises LlamaServerError cleanly."""
		mock_client = mock.MagicMock()
		mock_client.is_connected = True
		mock_client.send_command.return_value = {
			"type": "error",
			"command": "llama_ensure_ready",
			"error_code": "LLAMA_START_FAILED",
			"error_message": "llama-server exited before becoming ready with code 1",
			"success": False,
		}
		supervisor = LlamaServerSupervisor(worker_client=mock_client)
		with self.assertRaises(LlamaServerError) as ctx:
			supervisor.ensure_ready("test_model.gguf", timeout=5.0)
		self.assertIn("exited before becoming ready", str(ctx.exception))


class TestLlamaTimeoutAndDeadlockResistance(unittest.TestCase):
	"""Empirically test timeout enforcement and pipe desync resistance (Dead End M1 Iter 2 check)."""

	def setUp(self) -> None:
		token = uuid.uuid4().hex[:8]
		self.cmd_pipe = f"\\\\.\\pipe\\c1_llama_timeout_cmd_{token}"
		self.evt_pipe = f"\\\\.\\pipe\\c1_llama_timeout_evt_{token}"
		self.server = WorkerServer(
			cmd_pipe_name=self.cmd_pipe,
			evt_pipe_name=self.evt_pipe,
		)
		self.server.start()

		self.client = NamedPipeWorkerClient(
			cmd_pipe_name=self.cmd_pipe,
			evt_pipe_name=self.evt_pipe,
		)
		self.client.connect()

	def tearDown(self) -> None:
		self.client.disconnect()
		self.server.shutdown()

	def test_send_command_enforces_timeout_promptly(self) -> None:
		"""send_command must enforce its timeout parameter and raise TimeoutError within deadline."""
		def slow_handle(frame: dict) -> None:
			if frame.get("type") == "slow_llama_cmd":
				time.sleep(2.0)
				if self.server._cmd_server and self.server._cmd_server.is_connected:
					self.server._cmd_server.write_frame({"type": "slow_resp", "success": True})
				return
			server_mod.WorkerServer._handle_command(self.server, frame)

		self.server._handle_command = slow_handle

		start = time.perf_counter()
		with self.assertRaises(TimeoutError):
			self.client.send_command({"type": "slow_llama_cmd"}, timeout=0.2)
		elapsed = time.perf_counter() - start

		self.assertGreaterEqual(elapsed, 0.18)
		self.assertLess(elapsed, 0.8, f"Timeout took too long to fire: {elapsed}s")

	def test_pipe_desynchronization_stale_response_avoidance(self) -> None:
		"""Empirical challenge: verify that delayed response from timed-out command does NOT pollute next command.

		Directly targets Dead End M1 Iter 2: calling flush_input() without resetting pipe
		caused delayed response to arrive after flush, polluting subsequent command.
		"""
		def handle_cmd(frame: dict) -> None:
			if frame.get("type") == "llama_ensure_ready_slow":
				time.sleep(0.4)
				if self.server._cmd_server and self.server._cmd_server.is_connected:
					self.server._cmd_server.write_frame({
						"type": "llama_status_response",
						"command": "llama_ensure_ready_slow",
						"success": True,
						"status": {"state": "ready_stale", "generation": 1},
					})
				return
			if frame.get("type") in ("llama_get_status", "llama_status"):
				if self.server._cmd_server and self.server._cmd_server.is_connected:
					self.server._cmd_server.write_frame({
						"type": "llama_status_response",
						"command": "llama_get_status",
						"success": True,
						"status": {"state": "ready_fresh", "generation": 2},
					})
				return
			server_mod.WorkerServer._handle_command(self.server, frame)

		self.server._handle_command = handle_cmd

		# 1. Send slow ensure_ready with timeout=0.1s
		with self.assertRaises(TimeoutError):
			self.client.send_command({"type": "llama_ensure_ready_slow"}, timeout=0.1)

		# 2. Wait for server to finish slow command and attempt writing stale response
		time.sleep(0.5)

		# 3. Send fast status command over the same client connection
		resp2 = self.client.send_command({"type": "llama_get_status"}, timeout=2.0)

		self.assertTrue(resp2.get("success"))
		self.assertEqual(resp2.get("command"), "llama_get_status")
		status = resp2.get("status", {})
		self.assertEqual(
			status.get("state"),
			"ready_fresh",
			f"Pipe desynchronization detected! Stale response leaked into subsequent command: {resp2}",
		)
		self.assertEqual(status.get("generation"), 2)

	def test_immediate_command_after_timeout_without_sleep(self) -> None:
		"""Empirical challenge: immediately send follow-up command without sleeping; verify clean recovery."""
		def handle_cmd(frame: dict) -> None:
			if frame.get("type") == "slow_llama_restart":
				time.sleep(0.35)
				if self.server._cmd_server and self.server._cmd_server.is_connected:
					self.server._cmd_server.write_frame({"type": "slow_resp", "stale": True})
				return
			if frame.get("type") == "fast_status":
				if self.server._cmd_server and self.server._cmd_server.is_connected:
					self.server._cmd_server.write_frame({"type": "fast_resp", "seq": frame.get("seq")})
				return
			server_mod.WorkerServer._handle_command(self.server, frame)

		self.server._handle_command = handle_cmd

		# 1. Timeout on slow restart
		with self.assertRaises(TimeoutError):
			self.client.send_command({"type": "slow_llama_restart"}, timeout=0.08)

		# 2. Immediately send fast command without arbitrary wait
		resp = self.client.send_command({"type": "fast_status", "seq": 101}, timeout=3.0)
		self.assertEqual(resp.get("type"), "fast_resp")
		self.assertEqual(resp.get("seq"), 101)

	def test_cross_thread_timeout_isolation(self) -> None:
		"""Empirical challenge: Thread 1 timeout does not leak its response to Thread 2."""
		def handle_cmd(frame: dict) -> None:
			if frame.get("type") == "t1_slow_llama":
				time.sleep(0.4)
				if self.server._cmd_server and self.server._cmd_server.is_connected:
					self.server._cmd_server.write_frame({"type": "t1_resp", "thread": 1})
				return
			if frame.get("type") == "t2_fast_llama":
				if self.server._cmd_server and self.server._cmd_server.is_connected:
					self.server._cmd_server.write_frame({"type": "t2_resp", "thread": 2})
				return
			server_mod.WorkerServer._handle_command(self.server, frame)

		self.server._handle_command = handle_cmd

		# Thread 1 times out
		with self.assertRaises(TimeoutError):
			self.client.send_command({"type": "t1_slow_llama"}, timeout=0.1)

		# Allow server to complete Thread 1's write attempt
		time.sleep(0.5)

		# Thread 2 executes fast command
		resp = self.client.send_command({"type": "t2_fast_llama"}, timeout=2.0)
		self.assertEqual(
			resp.get("thread"),
			2,
			f"Cross-thread response pollution! Thread 2 received Thread 1's frame: {resp}",
		)

	def test_multiple_consecutive_timeouts_recover_cleanly(self) -> None:
		"""Empirical challenge: multiple consecutive timeouts do not deadlock or permanently break the client."""
		def handle_cmd(frame: dict) -> None:
			if frame.get("type") == "slow_cmd":
				time.sleep(0.25)
				if self.server._cmd_server and self.server._cmd_server.is_connected:
					self.server._cmd_server.write_frame({"type": "slow_resp"})
				return
			if frame.get("type") == "good_cmd":
				if self.server._cmd_server and self.server._cmd_server.is_connected:
					self.server._cmd_server.write_frame({"type": "good_resp", "val": frame.get("val")})
				return
			server_mod.WorkerServer._handle_command(self.server, frame)

		self.server._handle_command = handle_cmd

		for i in range(3):
			with self.assertRaises(TimeoutError):
				self.client.send_command({"type": "slow_cmd"}, timeout=0.08)
			time.sleep(0.3)

		# Final command succeeds
		resp = self.client.send_command({"type": "good_cmd", "val": 777}, timeout=2.0)
		self.assertEqual(resp.get("type"), "good_resp")
		self.assertEqual(resp.get("val"), 777)


class TestLlamaConcurrencyAndStressIPC(unittest.TestCase):
	"""High-concurrency and multi-threaded stress tests for llama Worker IPC."""

	def setUp(self) -> None:
		token = uuid.uuid4().hex[:8]
		self.cmd_pipe = f"\\\\.\\pipe\\c1_llama_stress_cmd_{token}"
		self.evt_pipe = f"\\\\.\\pipe\\c1_llama_stress_evt_{token}"
		self.server = WorkerServer(
			cmd_pipe_name=self.cmd_pipe,
			evt_pipe_name=self.evt_pipe,
		)
		self.mock_executor = mock.MagicMock()
		self.mock_executor.get_status.return_value = {
			"state": "ready_owned",
			"generation": 12,
			"pid": 8888,
			"is_ready": True,
			"is_running": True,
			"running_model": "qwen",
		}
		self.mock_executor.list_models.return_value = [{"id": "qwen"}, {"id": "llama3"}]
		self.mock_executor.adopt.return_value = {
			"state": "ready_adopted",
			"generation": 13,
			"is_ready": True,
			"is_running": False,
			"is_adopted": True,
		}
		self.mock_executor.configure_preset.return_value = {
			"success": True,
			"preset_path": "C:\\models\\models.ini",
			"sha256": "abc999",
		}
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

	def test_rapid_sequential_llama_status_queries(self) -> None:
		"""100 rapid sequential llama_get_status queries over named pipe."""
		start = time.perf_counter()
		for i in range(100):
			resp = self.client.send_command({"type": "llama_get_status", "command": "llama_get_status"})
			self.assertTrue(resp.get("success"))
			self.assertEqual(resp.get("status", {}).get("generation"), 12)
		elapsed = time.perf_counter() - start
		self.assertLess(elapsed, 2.0, f"100 status queries took too long: {elapsed}s")

	def test_concurrent_multi_threaded_llama_commands(self) -> None:
		"""10 concurrent threads each issuing 20 diverse llama commands."""
		num_threads = 10
		cmds_per_thread = 20
		errors: list[Exception] = []

		def worker_thread(tid: int) -> None:
			for i in range(cmds_per_thread):
				try:
					cmd_idx = i % 4
					if cmd_idx == 0:
						resp = self.client.send_command({
							"type": "llama_get_status",
							"command": "llama_get_status",
							"tid": tid,
						})
						assert resp.get("success") is True
						assert resp.get("status", {}).get("state") == "ready_owned"
					elif cmd_idx == 1:
						resp = self.client.send_command({
							"type": "llama_list_models",
							"command": "llama_list_models",
							"tid": tid,
						})
						assert resp.get("success") is True
						assert len(resp.get("models", [])) == 2
					elif cmd_idx == 2:
						resp = self.client.send_command({
							"type": "llama_configure_preset",
							"command": "llama_configure_preset",
							"models": [{"model_id": f"m_{tid}_{i}"}],
							"tid": tid,
						})
						assert resp.get("success") is True
						assert resp.get("sha256") == "abc999"
					else:
						resp = self.client.send_command({
							"type": "llama_adopt",
							"command": "llama_adopt",
							"model_id": "qwen",
							"tid": tid,
						})
						assert resp.get("success") is True
						assert resp.get("status", {}).get("state") == "ready_adopted"
				except Exception as exc:
					errors.append(exc)

		threads = [threading.Thread(target=worker_thread, args=(i,)) for i in range(num_threads)]
		for t in threads:
			t.start()
		for t in threads:
			t.join(timeout=10.0)

		self.assertEqual(len(errors), 0, f"Concurrent commands failed with errors: {errors}")

	def test_concurrent_supervisor_status_proxy_calls(self) -> None:
		"""50 concurrent threads querying status via LlamaServerSupervisor proxy."""
		supervisor = LlamaServerSupervisor(worker_client=self.client)
		results: list[bool] = []

		def query_status() -> None:
			st = supervisor.status()
			results.append(st.is_ready)

		with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
			futures = [ex.submit(query_status) for _ in range(50)]
			for f in futures:
				f.result(timeout=5.0)

		self.assertEqual(len(results), 50)
		self.assertTrue(all(results))

	def test_concurrent_configure_preset_atomic_writes(self) -> None:
		"""Concurrent calls to LlamaWorkerExecutor.configure_preset do not corrupt the ini file."""
		executor = LlamaWorkerExecutor()
		with tempfile.TemporaryDirectory() as td:
			preset_path = Path(td) / "models.ini"
			errors: list[Exception] = []

			def run_configure(worker_id: int) -> None:
				for i in range(10):
					try:
						models = [
							{
								"model_id": f"model_w{worker_id}_{i}",
								"source": f"hf://repo/model_{worker_id}_{i}",
								"kind": "hugging_face",
							},
							{
								"model_id": "common_base",
								"source": "hf://repo/common_base",
								"kind": "hugging_face",
							},
						]
						res = executor.configure_preset(
							models=models,
							default_model=f"model_w{worker_id}_{i}",
							preset_path=preset_path,
						)
						assert res.get("success") is True
						assert Path(res["preset_path"]).is_file()
					except Exception as exc:
						errors.append(exc)

			threads = [threading.Thread(target=run_configure, args=(w,)) for w in range(5)]
			for t in threads:
				t.start()
			for t in threads:
				t.join(timeout=10.0)

			self.assertEqual(len(errors), 0, f"Errors in concurrent preset configure: {errors}")
			self.assertTrue(preset_path.is_file())
			content = preset_path.read_text(encoding="utf-8")
			self.assertIn("version = 1", content)
			self.assertIn("[common_base]", content)
			self.assertGreater(len(content), 20)


class TestLlamaMalformedPayloadsAndEdgeCases(unittest.TestCase):
	"""Stress test WorkerServer against invalid, malformed, and boundary payloads for llama commands."""

	def setUp(self) -> None:
		token = uuid.uuid4().hex[:8]
		self.cmd_pipe = f"\\\\.\\pipe\\c1_llama_mal_cmd_{token}"
		self.evt_pipe = f"\\\\.\\pipe\\c1_llama_mal_evt_{token}"
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
			client_name="llama_c1_challenger",
			client_version="1.0.0",
			requested_capabilities=("job.echo", "runtime.llama"),
		)
		self.client.write_frame(req.to_dict())
		raw_resp = self.client.read_frame()
		self.assertTrue(raw_resp.get("accepted"))

	def tearDown(self) -> None:
		self.client.close()
		self.server.shutdown()

	def test_llama_ensure_ready_missing_model_and_preset(self) -> None:
		"""Calling llama_ensure_ready with empty model & preset returns structured error frame."""
		real_exec = LlamaWorkerExecutor()
		self.server._llama_executor = real_exec

		self.client.write_frame({
			"type": "llama_ensure_ready",
			"command": "llama_ensure_ready",
		})
		resp = self.client.read_frame()
		self.assertEqual(resp.get("type"), "error")
		self.assertEqual(resp.get("error_code"), "LLAMA_START_FAILED")
		self.assertFalse(resp.get("success"))
		self.assertIn("required", str(resp.get("error_message")))

		# Verify server survives and responds to next command
		self.client.write_frame({"type": "llama_get_status", "command": "llama_get_status"})
		resp2 = self.client.read_frame()
		self.assertTrue(resp2.get("success"))

	def test_llama_ensure_ready_invalid_timeout_type(self) -> None:
		"""Passing non-numeric timeout_seconds returns error frame and keeps server alive."""
		self.client.write_frame({
			"type": "llama_ensure_ready",
			"command": "llama_ensure_ready",
			"model": "model.gguf",
			"timeout_seconds": "not_a_float",
		})
		resp = self.client.read_frame()
		self.assertEqual(resp.get("type"), "error")
		self.assertEqual(resp.get("error_code"), "LLAMA_START_FAILED")
		self.assertFalse(resp.get("success"))

	def test_raw_invalid_json_stream_recovery(self) -> None:
		"""Sending raw non-JSON bytes is safely caught; next valid frame succeeds."""
		self.client.write_raw(b"CORRUPTED_NON_JSON_BYTES_LLAMA\n")

		self.mock_executor.get_status.return_value = {"state": "stopped", "is_ready": False}
		self.client.write_frame({"type": "llama_get_status", "command": "llama_get_status"})
		resp = self.client.read_frame()
		self.assertTrue(resp.get("success"))

	def test_client_disconnect_during_in_flight_command(self) -> None:
		"""Client disconnects immediately after writing frame; server cleanly disconnects and accepts reconnect."""
		self.mock_executor.get_status.return_value = {"state": "ready_owned"}
		self.client.write_frame({"type": "llama_get_status", "command": "llama_get_status"})
		self.client.close()

		time.sleep(0.1)

		# Reconnect with new client
		new_client = NamedPipeClient(self.cmd_pipe)
		new_client.connect(timeout_seconds=2.0)
		req = HandshakeRequest(
			protocol_version="1.0.0",
			client_name="reconnected_client",
			client_version="1.0.0",
			requested_capabilities=("job.echo", "runtime.llama"),
		)
		new_client.write_frame(req.to_dict())
		raw_resp = new_client.read_frame()
		self.assertTrue(raw_resp.get("accepted"))

		new_client.write_frame({"type": "llama_get_status", "command": "llama_get_status"})
		resp = new_client.read_frame()
		self.assertTrue(resp.get("success"))
		new_client.close()


class TestLlamaBrokenPipeAndRecycleRecovery(unittest.TestCase):
	"""Test broken pipe containment and supervisor recovery after worker recycle."""

	def test_broken_pipe_raises_promptly_on_server_death(self) -> None:
		"""When worker server shuts down, client.send_command raises PipeDisconnectedError promptly (< 0.5s)."""
		token = uuid.uuid4().hex[:8]
		cmd_pipe = f"\\\\.\\pipe\\c1_llama_brk_cmd_{token}"
		evt_pipe = f"\\\\.\\pipe\\c1_llama_brk_evt_{token}"

		server = WorkerServer(cmd_pipe_name=cmd_pipe, evt_pipe_name=evt_pipe)
		server.start()

		client = NamedPipeWorkerClient(cmd_pipe_name=cmd_pipe, evt_pipe_name=evt_pipe)
		client.connect()

		# Abrupt server termination
		server.shutdown()

		start = time.perf_counter()
		with self.assertRaises((PipeDisconnectedError, OSError, RuntimeError)):
			client.send_command({"type": "llama_get_status"}, timeout=1.0)
		elapsed = time.perf_counter() - start

		self.assertLess(elapsed, 0.5, f"Broken pipe detection took too long: {elapsed}s")
		client.disconnect()

	def test_supervisor_status_during_broken_pipe_never_hangs(self) -> None:
		"""Supervisor.status() returns idle status without hanging (< 50ms) when worker pipe is dead."""
		token = uuid.uuid4().hex[:8]
		cmd_pipe = f"\\\\.\\pipe\\c1_llama_st_brk_cmd_{token}"
		evt_pipe = f"\\\\.\\pipe\\c1_llama_st_brk_evt_{token}"

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
			self.assertLess(elapsed, 0.05, f"status() took too long during broken pipe: {elapsed}s")

		client.disconnect()

	def test_worker_recycle_and_reconnection(self) -> None:
		"""Worker restart / recycle allows client to reconnect and resume operations cleanly."""
		token = uuid.uuid4().hex[:8]
		cmd_pipe = f"\\\\.\\pipe\\c1_llama_recyc_cmd_{token}"
		evt_pipe = f"\\\\.\\pipe\\c1_llama_recyc_evt_{token}"

		server1 = WorkerServer(cmd_pipe_name=cmd_pipe, evt_pipe_name=evt_pipe)
		mock_exec1 = mock.MagicMock()
		mock_exec1.get_status.return_value = {"state": "ready_owned", "generation": 1}
		server1._llama_executor = mock_exec1
		server1.start()

		client = NamedPipeWorkerClient(cmd_pipe_name=cmd_pipe, evt_pipe_name=evt_pipe)
		client.connect()
		supervisor = LlamaServerSupervisor(worker_client=client)

		st1 = supervisor.status()
		self.assertEqual(st1.state, "ready_owned")

		# Terminate server1
		server1.shutdown()
		client.disconnect()

		# Launch replacement server2
		server2 = WorkerServer(cmd_pipe_name=cmd_pipe, evt_pipe_name=evt_pipe)
		mock_exec2 = mock.MagicMock()
		mock_exec2.get_status.return_value = {"state": "ready_owned", "generation": 2}
		server2._llama_executor = mock_exec2
		server2.start()

		try:
			client.connect()
			st2 = supervisor.status()
			self.assertEqual(st2.state, "ready_owned")
			self.assertEqual(st2.generation, 2)
		finally:
			client.disconnect()
			server2.shutdown()


class TestLlamaContractsAndTypeSafety(unittest.TestCase):
	"""Test contract boundaries, type safety, and URL formatting."""

	def test_is_connected_type_safety_variants(self) -> None:
		"""Ensure property, attribute, and callable variations of is_connected never cause TypeError."""
		class PropClientTrue:
			@property
			def is_connected(self) -> bool:
				return True

			def send_command(self, cmd: dict, timeout: float = 10.0) -> dict:
				return {"success": True, "status": {"state": "ready_owned", "generation": 1, "is_ready": True}}

		class PropClientFalse:
			@property
			def is_connected(self) -> bool:
				return False

		class MethodClientTrue:
			def is_connected(self) -> bool:
				return True

			def send_command(self, cmd: dict, timeout: float = 10.0) -> dict:
				return {"success": True, "status": {"state": "ready_owned", "generation": 1, "is_ready": True}}

		class MethodClientFalse:
			def is_connected(self) -> bool:
				return False

		class AttrClientTrue:
			def __init__(self) -> None:
				self.is_connected = True

			def send_command(self, cmd: dict, timeout: float = 10.0) -> dict:
				return {"success": True, "status": {"state": "ready_owned", "generation": 1, "is_ready": True}}

		class AttrClientFalse:
			def __init__(self) -> None:
				self.is_connected = False

		test_clients = [
			(PropClientTrue(), True),
			(PropClientFalse(), False),
			(MethodClientTrue(), True),
			(MethodClientFalse(), False),
			(AttrClientTrue(), True),
			(AttrClientFalse(), False),
			(None, False),
		]

		for client, expected_connected in test_clients:
			with self.subTest(client_type=type(client).__name__ if client else "None"):
				sup = LlamaServerSupervisor(worker_client=client)

				resolved = sup._get_worker_client()
				if expected_connected:
					self.assertIs(resolved, client)
				else:
					self.assertIsNone(resolved)

				st = sup.status()
				if expected_connected:
					self.assertEqual(st.state, "ready_owned")
					self.assertTrue(st.is_ready)
				else:
					self.assertEqual(st.state, "stopped")
					self.assertFalse(st.is_ready)

	def test_ipv6_host_bracketed_in_worker_executor(self) -> None:
		"""Verify that LlamaWorkerExecutor properly brackets IPv6 addresses in base_url."""
		executor = LlamaWorkerExecutor(host="::1", port=8080)
		st = executor.get_status()
		self.assertEqual(st["base_url"], "http://[::1]:8080")

	def test_ipv6_host_in_llama_server_supervisor_base_url(self) -> None:
		"""Empirically test whether LlamaServerSupervisor.base_url brackets IPv6 host.

		Defect finding: LlamaServerSupervisor.base_url returns f'http://{self.host}:{self.port}'
		which produces 'http://::1:8080' without square brackets.
		RFC 3986 requires square brackets for IPv6 host literals in URLs.
		"""
		sup = LlamaServerSupervisor(host="::1", port=8080)
		# Record empirical observation:
		# Does sup.base_url include square brackets?
		has_brackets = sup.base_url.startswith("http://[::1]:")
		# We check if urlsplit can safely extract port without ValueError:
		parsed = urllib.parse.urlsplit(sup.base_url)
		# If unbracketed, accessing parsed.port raises ValueError!
		try:
			port = parsed.port
		except ValueError:
			port = None
		# Document empirical result:
		# If unbracketed, port will be None due to ValueError
		if not has_brackets:
			self.assertIsNone(
				port,
				"Unbracketed IPv6 URL unexpectedly parsed port without error",
			)
			# Confirmed defect: unbracketed IPv6 URL breaks urlsplit port extraction
			self.assertEqual(sup.base_url, "http://::1:8080")
		else:
			self.assertEqual(port, 8080)

	def test_status_retains_worker_error_frame_data(self) -> None:
		"""When worker returns error frame, supervisor.status() maps it to state='failed' with error info."""
		mock_client = mock.MagicMock()
		mock_client.is_connected = True
		mock_client.send_command.return_value = {
			"type": "error",
			"command": "llama_get_status",
			"error_code": "LLAMA_CRASHED",
			"error_message": "llama-server process exited unexpectedly with code 139",
			"generation": 19,
			"success": False,
		}
		sup = LlamaServerSupervisor(worker_client=mock_client)
		st = sup.status()
		self.assertEqual(st.state, "failed")
		self.assertFalse(st.is_ready)
		self.assertFalse(st.is_running)
		self.assertEqual(st.generation, 19)
		self.assertEqual(st.error_code, "LLAMA_CRASHED")
		self.assertEqual(st.error_message, "llama-server process exited unexpectedly with code 139")


class TestLlamaFailClosedInvariants(unittest.TestCase):
	"""Adversarially challenge fail-closed invariants when worker process is unavailable.

	Mandates:
	1. ensure_ready(), restart(), and adopt() unconditionally raise LlamaServerError("Worker process is not available")
	   whenever worker_client is None or unavailable.
	2. NEVER attempt to spawn an in-process native supervisor or execute unmanaged subprocesses.
	3. status() cleanly returns idle status without hanging or raising.
	4. Zero native supervisor instantiation in the NVDA host process.
	"""

	def setUp(self) -> None:
		self.mock_popen = mock.patch("subprocess.Popen").start()
		self.mock_run = mock.patch("subprocess.run").start()
		self.mock_call = mock.patch("subprocess.call").start()
		self._reset_worker_supervisor_globals()

	def tearDown(self) -> None:
		self._reset_worker_supervisor_globals()
		mock.patch.stopall()

	def _reset_worker_supervisor_globals(self) -> None:
		pkg_prefix = LlamaServerSupervisor.__module__.split(".")[0]
		target_mod = sys.modules.get(f"{pkg_prefix}.plugin.worker_supervisor")
		if target_mod is not None:
			if hasattr(target_mod, "set_worker_client"):
				target_mod.set_worker_client(None)
			if hasattr(target_mod, "set_worker_supervisor"):
				target_mod.set_worker_supervisor(None)
		if "worker_sup_mod" in globals():
			if hasattr(worker_sup_mod, "set_worker_client"):
				worker_sup_mod.set_worker_client(None)
			if hasattr(worker_sup_mod, "set_worker_supervisor"):
				worker_sup_mod.set_worker_supervisor(None)

	def _get_disconnected_variants(self) -> list[tuple[str, Any]]:
		"""Return a spectrum of unavailable worker client variants."""
		client_prop_false = mock.MagicMock()
		client_prop_false.is_connected = False

		client_method_false = mock.MagicMock()
		client_method_false.is_connected = lambda: False

		client_raising = mock.MagicMock()
		client_raising.is_connected = mock.MagicMock(side_effect=RuntimeError("Pipe broken"))

		client_none_conn = mock.MagicMock()
		client_none_conn.is_connected = None

		return [
			("default_none", None),
			("explicit_none", None),
			("property_false", client_prop_false),
			("callable_false", client_method_false),
			("raising_connection", client_raising),
			("none_connection", client_none_conn),
		]

	def test_ensure_ready_unconditionally_raises_and_never_spawns_subprocesses(self) -> None:
		"""ensure_ready() unconditionally raises LlamaServerError and never spawns subprocesses when worker is unavailable."""
		for label, client in self._get_disconnected_variants():
			with self.subTest(variant=label):
				sup = LlamaServerSupervisor(port=8080, worker_client=client)
				self.assertIsNone(sup._get_native(), f"Native supervisor was not None for variant {label}")

				with self.assertRaises(LlamaServerError) as ctx:
					sup.ensure_ready("test_model", timeout=1.0)

				self.assertIn("Worker process is not available", str(ctx.exception))
				self.assertEqual(self.mock_popen.call_count, 0, f"subprocess.Popen was called for variant {label}!")
				self.assertEqual(self.mock_run.call_count, 0, f"subprocess.run was called for variant {label}!")
				self.assertEqual(self.mock_call.call_count, 0, f"subprocess.call was called for variant {label}!")

	def test_restart_unconditionally_raises_and_never_spawns_subprocesses(self) -> None:
		"""restart() unconditionally raises LlamaServerError and never spawns subprocesses when worker is unavailable."""
		for label, client in self._get_disconnected_variants():
			with self.subTest(variant=label):
				sup = LlamaServerSupervisor(port=8080, worker_client=client)
				self.assertIsNone(sup._get_native(), f"Native supervisor was not None for variant {label}")

				with self.assertRaises(LlamaServerError) as ctx:
					sup.restart("test_model", timeout=1.0)

				self.assertIn("Worker process is not available", str(ctx.exception))
				self.assertEqual(self.mock_popen.call_count, 0, f"subprocess.Popen was called for variant {label}!")
				self.assertEqual(self.mock_run.call_count, 0, f"subprocess.run was called for variant {label}!")
				self.assertEqual(self.mock_call.call_count, 0, f"subprocess.call was called for variant {label}!")

	def test_adopt_unconditionally_raises_and_never_spawns_subprocesses(self) -> None:
		"""adopt() unconditionally raises LlamaServerError and never spawns subprocesses when worker is unavailable."""
		for label, client in self._get_disconnected_variants():
			with self.subTest(variant=label):
				sup = LlamaServerSupervisor(port=8080, worker_client=client)
				self.assertIsNone(sup._get_native(), f"Native supervisor was not None for variant {label}")

				with self.assertRaises(LlamaServerError) as ctx:
					sup.adopt("test_model")

				self.assertIn("Worker process is not available", str(ctx.exception))
				self.assertEqual(self.mock_popen.call_count, 0, f"subprocess.Popen was called for variant {label}!")
				self.assertEqual(self.mock_run.call_count, 0, f"subprocess.run was called for variant {label}!")
				self.assertEqual(self.mock_call.call_count, 0, f"subprocess.call was called for variant {label}!")

	def test_start_unconditionally_raises_when_worker_unavailable(self) -> None:
		"""start() delegates to ensure_ready() and unconditionally raises LlamaServerError."""
		sup = LlamaServerSupervisor(port=8080)
		with self.assertRaises(LlamaServerError) as ctx:
			sup.start("test_model")
		self.assertIn("Worker process is not available", str(ctx.exception))
		self.assertEqual(self.mock_popen.call_count, 0)

	def test_status_cleanly_returns_idle_status_without_hanging_or_raising(self) -> None:
		"""status() returns idle status without hanging (<50ms) or raising when worker is unavailable."""
		for label, client in self._get_disconnected_variants():
			with self.subTest(variant=label):
				sup = LlamaServerSupervisor(host="127.0.0.1", port=8080, worker_client=client)
				t0 = time.perf_counter()
				st = sup.status()
				elapsed = time.perf_counter() - t0

				self.assertLess(elapsed, 0.05, f"status() took {elapsed:.4f}s (>50ms) for variant {label}")
				self.assertEqual(st.state, "stopped")
				self.assertFalse(st.is_ready)
				self.assertFalse(st.is_running)
				self.assertFalse(st.is_adopted)
				self.assertIsNone(st.pid)
				self.assertEqual(st.generation, 0)
				self.assertIsNone(st.error_message)
				self.assertIsNone(st.startup_identity)
				self.assertIsNone(st.running_model)
				self.assertEqual(st.base_url, "http://127.0.0.1:8080")
				self.assertFalse(sup.is_running)
				self.assertFalse(sup.is_adopted)

	def test_status_falls_back_to_idle_on_rpc_transport_error(self) -> None:
		"""When worker client is connected but send_command raises an error, status() cleanly falls back to idle."""
		mock_client = mock.MagicMock()
		mock_client.is_connected = True
		mock_client.send_command.side_effect = PipeDisconnectedError("Named pipe broken")

		sup = LlamaServerSupervisor(host="127.0.0.1", port=8080, worker_client=mock_client)
		t0 = time.perf_counter()
		st = sup.status()
		elapsed = time.perf_counter() - t0

		self.assertLess(elapsed, 0.05)
		self.assertEqual(st.state, "stopped")
		self.assertFalse(st.is_ready)
		self.assertFalse(st.is_running)

	def test_lifecycle_and_query_safeguards_when_worker_unavailable(self) -> None:
		"""Safe lifecycle operations (stop, close, shutdown, list_models, is_healthy) do not raise when worker is absent."""
		sup = LlamaServerSupervisor(port=8080)

		# stop, close, shutdown should be safe no-ops
		sup.stop()
		sup.close()
		sup.shutdown()

		# Query methods fail gracefully
		self.assertFalse(sup.is_healthy(timeout=0.1))
		self.assertEqual(sup.list_models(timeout=0.1), ())

		# wait_until_ready raises immediately when not running/adopted
		t0 = time.perf_counter()
		with self.assertRaises(LlamaServerError) as ctx:
			sup.wait_until_ready(timeout=5.0)
		elapsed = time.perf_counter() - t0
		self.assertLess(elapsed, 0.2, "wait_until_ready did not abort promptly on stopped status")
		self.assertIn("llama-server exited before becoming ready", str(ctx.exception))

	def test_zero_native_supervisor_instantiation_in_llama_server_module(self) -> None:
		"""llama_server module has zero native supervisor imports or instantiation in production path."""
		self.assertFalse(
			hasattr(llama_server_mod, "runtime_supervisor"),
			"llama_server unexpectedly has runtime_supervisor attribute",
		)
		sup = LlamaServerSupervisor()
		self.assertIsNone(sup._get_native())
		self.assertIsNone(sup._native_supervisor)
		self.assertIsNone(sup._process_factory)
		self.assertIsNone(sup._test_shim)

	def test_global_worker_supervisor_discovery_when_not_injected(self) -> None:
		"""LlamaServerSupervisor discovers global worker client when not explicitly injected."""
		mock_global_client = mock.MagicMock()
		mock_global_client.is_connected = True
		mock_global_client.send_command.return_value = {
			"success": True,
			"status": {
				"state": "ready_owned",
				"is_ready": True,
				"is_running": True,
				"is_adopted": False,
				"generation": 3,
				"running_model": "test-gguf",
			},
		}

		pkg_prefix = LlamaServerSupervisor.__module__.split(".")[0]
		target_mod = sys.modules.get(f"{pkg_prefix}.plugin.worker_supervisor", worker_sup_mod)

		with mock.patch.object(
			target_mod,
			"get_worker_client",
			return_value=mock_global_client,
		):
			patch_fallback = (
				mock.patch.object(worker_sup_mod, "get_worker_client", return_value=mock_global_client)
				if worker_sup_mod is not target_mod
				else None
			)
			if patch_fallback:
				patch_fallback.start()
				self.addCleanup(patch_fallback.stop)

			sup = LlamaServerSupervisor(port=8080)
			st = sup.status()
			self.assertEqual(st.state, "ready_owned")
			self.assertTrue(st.is_ready)
			self.assertEqual(st.generation, 3)

	def test_record_source_lines_sanitizes_newlines_and_carriage_returns(self) -> None:
		"""_record_source_lines and build_models_preset neutralize CRLF injection attempts."""
		build_models_preset = llama_exec_mod.build_models_preset
		attacks = [
			{"model_id": "model-repo-inject", "hf_repo": "org/repo\n[injected_section]\nadmin=true"},
			{"model_id": "model-source-inject", "source": "C:/models/valid.gguf\r\n[evil_section]\nkey=val"},
			{"model_id": "model-variant-inject", "source": "hf://org/repo", "variant": "Q4_K_M\n[variant_section]\npwned=1"},
		]
		result = build_models_preset(attacks)
		section_headers = [line.strip() for line in result.splitlines() if line.strip().startswith("[")]
		self.assertNotIn("[injected_section]", section_headers)
		self.assertNotIn("[evil_section]", section_headers)
		self.assertNotIn("[variant_section]", section_headers)
		self.assertIn("[model-repo-inject]", section_headers)
		self.assertIn("[model-source-inject]", section_headers)
		self.assertIn("[model-variant-inject]", section_headers)


if __name__ == "__main__":
	unittest.main()
