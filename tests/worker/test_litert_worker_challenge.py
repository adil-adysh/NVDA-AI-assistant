# -*- coding: utf-8 -*-
"""Adversarial stress and edge-case empirical challenge tests for Slice 6 (LiteRT Worker).

Tests:
1. Malformed and invalid command payloads over Named Pipe IPC.
2. High-concurrency and rapid sequential requests (litert_get_status, lifecycle).
3. Timeout enforcement and CancelIoEx cancellation in NamedPipeWorkerClient.send_command.
4. Broken pipe / server crash recovery and isolation.
"""

from __future__ import annotations

import concurrent.futures
import sys
import threading
import time
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
NamedPipeServer = trans_mod.NamedPipeServer
PipeDisconnectedError = trans_mod.PipeDisconnectedError
NamedPipeWorkerClient = worker_client_mod.NamedPipeWorkerClient
WorkerServer = server_mod.WorkerServer
LiteRTWorkerExecutor = litert_exec_mod.LiteRTWorkerExecutor
LiteRTServerSupervisor = litert_server_mod.LiteRTServerSupervisor
LiteRTServerError = litert_server_mod.LiteRTServerError


class TestMalformedPayloadIPC(unittest.TestCase):
	"""Stress test WorkerServer against invalid, malformed, and adversarial payloads."""

	def setUp(self) -> None:
		token = uuid.uuid4().hex[:8]
		self.cmd_pipe = f"\\\\.\\pipe\\chal_malformed_cmd_{token}"
		self.evt_pipe = f"\\\\.\\pipe\\chal_malformed_evt_{token}"
		self.server = WorkerServer(
			cmd_pipe_name=self.cmd_pipe,
			evt_pipe_name=self.evt_pipe,
		)
		self.mock_executor = mock.MagicMock()
		self.server._litert_executor = self.mock_executor
		self.server.start()

		self.client = NamedPipeClient(self.cmd_pipe)
		self.client.connect(timeout_seconds=2.0)

		# Handshake
		req = HandshakeRequest(
			protocol_version="1.0.0",
			client_name="challenger",
			client_version="1.0.0",
			requested_capabilities=("job.echo", "runtime.litert"),
		)
		self.client.write_frame(req.to_dict())
		raw_resp = self.client.read_frame()
		self.assertTrue(raw_resp.get("accepted"))

	def tearDown(self) -> None:
		self.client.close()
		self.server.shutdown()

	def test_unknown_command_returns_structured_error(self) -> None:
		self.client.write_frame({"type": "unknown_cmd_foo_bar"})
		resp = self.client.read_frame()
		self.assertEqual(resp.get("type"), "error")
		self.assertEqual(resp.get("error_code"), "UNKNOWN_COMMAND")

	def test_empty_frame_returns_unknown_command(self) -> None:
		self.client.write_frame({})
		resp = self.client.read_frame()
		self.assertEqual(resp.get("type"), "error")
		self.assertEqual(resp.get("error_code"), "UNKNOWN_COMMAND")

	def test_non_string_command_type(self) -> None:
		self.client.write_frame({"type": 99999})
		resp = self.client.read_frame()
		self.assertEqual(resp.get("type"), "error")
		self.assertEqual(resp.get("error_code"), "UNKNOWN_COMMAND")

	def test_litert_ensure_ready_with_invalid_timeout_type(self) -> None:
		"""Pass non-numeric timeout_seconds to litert_ensure_ready."""
		self.client.write_frame({
			"type": "litert_ensure_ready",
			"command": "litert_ensure_ready",
			"timeout_seconds": "not-a-number",
		})
		resp = self.client.read_frame()
		self.assertEqual(resp.get("type"), "error")
		self.assertEqual(resp.get("error_code"), "LITERT_START_FAILED")
		self.assertFalse(resp.get("success"))

	def test_litert_ensure_ready_custom_port_propagation(self) -> None:
		"""Test whether custom host/port sent by LiteRTServerSupervisor are honored."""
		self.mock_executor.ensure_ready.return_value = {"state": "running", "is_ready": True}
		self.client.write_frame({
			"type": "litert_ensure_ready",
			"command": "litert_ensure_ready",
			"host": "127.0.0.1",
			"port": 9450,
			"timeout_seconds": 30.0,
		})
		resp = self.client.read_frame()
		self.assertTrue(resp.get("success"))
		call_kwargs = self.mock_executor.ensure_ready.call_args
		port_forwarded = "port" in (call_kwargs.kwargs or {})
		self.assertTrue(port_forwarded, "WorkerServer did not forward port to executor")
		self.assertEqual(call_kwargs.kwargs.get("port"), 9450)
		self.assertEqual(call_kwargs.kwargs.get("host"), "127.0.0.1")

	def test_client_abrupt_disconnect_during_command(self) -> None:
		"""Client sends a command and closes connection before reading response."""
		self.mock_executor.get_status.return_value = {"state": "ready"}
		self.client.write_frame({"type": "litert_get_status", "command": "litert_get_status"})
		# Client abruptly closes before reading frame
		self.client.close()

		# Give server time to handle write_frame and disconnect
		time.sleep(0.1)

		# Reconnect with a new client
		new_client = NamedPipeClient(self.cmd_pipe)
		new_client.connect(timeout_seconds=2.0)
		# Exchange handshake
		req = HandshakeRequest(
			protocol_version="1.0.0",
			client_name="reconnected_challenger",
			client_version="1.0.0",
			requested_capabilities=("job.echo", "runtime.litert"),
		)
		new_client.write_frame(req.to_dict())
		raw_resp = new_client.read_frame()
		self.assertTrue(raw_resp.get("accepted"))

		# Send command on new connection
		new_client.write_frame({"type": "litert_get_status", "command": "litert_get_status"})
		resp = new_client.read_frame()
		self.assertTrue(resp.get("success"))
		new_client.close()

	def test_litert_import_model_path_traversal_model_id(self) -> None:
		"""Attempt model_id with path traversal characters."""
		self.client.write_frame({
			"type": "litert_import_model",
			"command": "litert_import_model",
			"model_id": "../../windows/system32/cmd",
			"model_path": "C:\\some_model.litertlm",
		})
		resp = self.client.read_frame()
		self.assertEqual(resp.get("type"), "error")
		self.assertEqual(resp.get("error_code"), "LITERT_IMPORT_FAILED")
		self.assertFalse(resp.get("success"))

	def test_litert_import_model_nonexistent_file(self) -> None:
		"""Import a nonexistent model file."""
		executor = LiteRTWorkerExecutor()
		self.server._litert_executor = executor
		self.client.write_frame({
			"type": "litert_import_model",
			"command": "litert_import_model",
			"model_id": "valid-id",
			"model_path": "C:\\nonexistent_dir_9999\\ghost.litertlm",
		})
		resp = self.client.read_frame()
		self.assertEqual(resp.get("type"), "error")
		self.assertEqual(resp.get("error_code"), "LITERT_IMPORT_FAILED")
		self.assertIn("does not exist", str(resp.get("error_message")))

	def test_litert_import_huggingface_missing_args(self) -> None:
		"""Hugging Face import with empty repo or artifact."""
		executor = LiteRTWorkerExecutor()
		self.server._litert_executor = executor
		self.client.write_frame({
			"type": "litert_import_huggingface_model",
			"command": "litert_import_huggingface_model",
			"repository": "",
			"artifact": "",
			"model_id": "valid-id",
		})
		resp = self.client.read_frame()
		self.assertEqual(resp.get("type"), "error")
		self.assertEqual(resp.get("error_code"), "LITERT_IMPORT_FAILED")
		self.assertIn("required", str(resp.get("error_message")))

	def test_litert_rename_model_invalid_names(self) -> None:
		"""Model rename with forbidden characters."""
		self.server._litert_executor = LiteRTWorkerExecutor()
		self.client.write_frame({
			"type": "litert_rename_model",
			"command": "litert_rename_model",
			"old_id": "bad\\name",
			"new_id": "good-name",
		})
		resp = self.client.read_frame()
		self.assertEqual(resp.get("type"), "error")
		self.assertEqual(resp.get("error_code"), "LITERT_RENAME_FAILED")

	def test_raw_invalid_json_line_handling(self) -> None:
		"""Client writes raw invalid JSON bytes onto the named pipe."""
		# Write raw non-JSON line directly
		self.client.write_raw(b"THIS_IS_NOT_VALID_JSON\n")
		# The server catches ProtocolError during read_frame().
		# Now send a valid frame; check if server remains alive and responds
		self.mock_executor.get_status.return_value = {"state": "stopped", "is_ready": False}
		self.client.write_frame({"type": "litert_get_status", "command": "litert_get_status"})
		resp = self.client.read_frame()
		self.assertTrue(resp.get("success"))

	def test_server_recovers_and_serves_subsequent_request_after_error(self) -> None:
		"""Verify that receiving an invalid command does not poison the command loop."""
		self.client.write_frame({"type": "bogus_cmd"})
		resp1 = self.client.read_frame()
		self.assertEqual(resp1.get("type"), "error")

		# Followed immediately by valid litert_get_status
		self.mock_executor.get_status.return_value = {"state": "stopped", "is_ready": False}
		self.client.write_frame({"type": "litert_get_status", "command": "litert_get_status"})
		resp2 = self.client.read_frame()
		self.assertTrue(resp2.get("success"))
		self.assertEqual(resp2.get("status", {}).get("state"), "stopped")


class TestConcurrencyAndStressIPC(unittest.TestCase):
	"""High-throughput and multi-threaded stress tests for Worker IPC."""

	def setUp(self) -> None:
		token = uuid.uuid4().hex[:8]
		self.cmd_pipe = f"\\\\.\\pipe\\chal_stress_cmd_{token}"
		self.evt_pipe = f"\\\\.\\pipe\\chal_stress_evt_{token}"
		self.server = WorkerServer(
			cmd_pipe_name=self.cmd_pipe,
			evt_pipe_name=self.evt_pipe,
		)
		self.mock_executor = mock.MagicMock()
		self.mock_executor.get_status.return_value = {
			"state": "ready",
			"generation": 10,
			"pid": 5555,
			"is_ready": True,
		}
		self.mock_executor.list_models.return_value = ["model1", "model2"]
		self.mock_executor.adopt.return_value = {"state": "ready", "generation": 11}
		self.server._litert_executor = self.mock_executor
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
		"""Send 100 rapid sequential litert_get_status commands."""
		start = time.perf_counter()
		for i in range(100):
			resp = self.client.send_command({"type": "litert_get_status", "command": "litert_get_status"})
			self.assertTrue(resp.get("success"))
			self.assertEqual(resp.get("status", {}).get("generation"), 10)
		elapsed = time.perf_counter() - start
		# 100 round-trips over local pipe should complete quickly (< 2 seconds)
		self.assertLess(elapsed, 2.0)

	def test_concurrent_threads_calling_send_command(self) -> None:
		"""Multi-threaded stress test: 10 threads concurrently sending 20 commands each."""
		num_threads = 10
		cmds_per_thread = 20
		errors: list[Exception] = []

		def worker_thread(tid: int) -> None:
			for i in range(cmds_per_thread):
				try:
					if i % 3 == 0:
						resp = self.client.send_command({
							"type": "litert_get_status",
							"command": "litert_get_status",
							"thread_id": tid,
						})
						assert resp.get("success") is True
					elif i % 3 == 1:
						resp = self.client.send_command({
							"type": "litert_list_models",
							"command": "litert_list_models",
							"thread_id": tid,
						})
						assert resp.get("success") is True
						assert resp.get("models") == ["model1", "model2"]
					else:
						resp = self.client.send_command({
							"type": "litert_adopt",
							"command": "litert_adopt",
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

	def test_supervisor_proxy_concurrent_status_calls(self) -> None:
		"""Verify LiteRTServerSupervisor proxy under concurrent status() calls."""
		supervisor = LiteRTServerSupervisor(worker_client=self.client)
		results = []

		def query_status() -> None:
			st = supervisor.status()
			results.append(st.is_ready)

		with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
			futures = [ex.submit(query_status) for _ in range(50)]
			for f in futures:
				f.result(timeout=5.0)

		self.assertEqual(len(results), 50)
		self.assertTrue(all(results))

	def test_status_drops_error_message_on_worker_error(self) -> None:
		"""LiteRTServerSupervisor.status() retains error_message when worker returns error frame."""
		mock_client = mock.MagicMock()
		mock_client.is_connected = True
		mock_client.send_command.return_value = {
			"type": "error",
			"command": "litert_get_status",
			"error_code": "LITERT_STATUS_FAILED",
			"error_message": "Subprocess crashed with exit code 1",
			"success": False,
		}
		supervisor = LiteRTServerSupervisor(worker_client=mock_client)
		st = supervisor.status()
		self.assertEqual(st.state, "failed")
		self.assertEqual(st.error_message, "Subprocess crashed with exit code 1")


class TestTimeoutAndCancellation(unittest.TestCase):
	"""Test timeout handling and cancelled I/O in NamedPipeWorkerClient."""

	def setUp(self) -> None:
		token = uuid.uuid4().hex[:8]
		self.cmd_pipe = f"\\\\.\\pipe\\chal_timeout_cmd_{token}"
		self.evt_pipe = f"\\\\.\\pipe\\chal_timeout_evt_{token}"
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

	def test_disconnect_cancels_blocked_send_command(self) -> None:
		"""If a thread is blocked in send_command, calling disconnect() must cancel I/O with CancelIoEx."""
		# Simulate a server that hangs and never writes a response back for a special command
		server_received = threading.Event()

		original_handle = self.server._handle_command

		def blocking_handle(frame: dict) -> None:
			if frame.get("type") == "hang_forever":
				server_received.set()
				# Sleep indefinitely without writing response
				time.sleep(10.0)
				return
			original_handle(frame)

		self.server._handle_command = blocking_handle

		send_error: list[Exception] = []
		send_finished = threading.Event()

		def do_send() -> None:
			try:
				self.client.send_command({"type": "hang_forever"}, timeout=5.0)
			except Exception as exc:
				send_error.append(exc)
			finally:
				send_finished.set()

		t = threading.Thread(target=do_send, daemon=True)
		t.start()

		# Wait until server receives frame
		self.assertTrue(server_received.wait(timeout=2.0))
		# Thread t is now blocked in read_frame()
		time.sleep(0.1)

		# Now call disconnect() from another thread
		t0 = time.perf_counter()
		self.client.disconnect()

		# The blocked thread must unblock promptly (CancelIoEx)
		unblocked = send_finished.wait(timeout=2.0)
		elapsed = time.perf_counter() - t0
		self.assertTrue(unblocked, "Blocked thread failed to unblock after disconnect()")
		self.assertLess(elapsed, 1.5, f"Teardown took too long: {elapsed}s")
		self.assertEqual(len(send_error), 1)
		self.assertIsInstance(send_error[0], (PipeDisconnectedError, OSError))

	def test_send_command_timeout_behavior(self) -> None:
		"""Empirically test whether send_command actually enforces its timeout parameter."""
		# Note: NamedPipeWorkerClient.send_command(cmd, timeout=0.2)
		# If the server does not respond within timeout, does send_command raise TimeoutError?
		server_received = threading.Event()

		def slow_handle(frame: dict) -> None:
			if frame.get("type") == "slow_cmd":
				server_received.set()
				time.sleep(2.0)  # Sleeps 2s
				if self.server._cmd_server and self.server._cmd_server.is_connected:
					self.server._cmd_server.write_frame({"type": "slow_resp", "success": True})
				return

		self.server._handle_command = slow_handle

		start_time = time.perf_counter()
		resp = None
		try:
			# Request timeout of 0.2 seconds
			resp = self.client.send_command({"type": "slow_cmd"}, timeout=0.2)
			elapsed = time.perf_counter() - start_time
			timed_out = False
		except TimeoutError:
			elapsed = time.perf_counter() - start_time
			timed_out = True

		self.timeout_enforced = timed_out
		self.elapsed_time = elapsed
		self.assertTrue(timed_out, f"send_command failed to enforce timeout: returned {resp} in {elapsed}s")
		self.assertLess(elapsed, 1.0, f"send_command timeout took too long: {elapsed}s")

	def test_subsequent_command_after_timeout_remains_uncorrupted(self) -> None:
		"""Empirical challenge: verify that subsequent commands after a TimeoutError remain uncorrupted."""
		server_received = threading.Event()

		def slow_handle(frame: dict) -> None:
			if frame.get("type") == "slow_cmd":
				server_received.set()
				time.sleep(0.4)
				if self.server._cmd_server and self.server._cmd_server.is_connected:
					self.server._cmd_server.write_frame({"type": "slow_resp", "success": True})
				return
			if frame.get("type") == "fast_status":
				if self.server._cmd_server and self.server._cmd_server.is_connected:
					self.server._cmd_server.write_frame({"type": "fast_status_resp", "state": "ready"})
				return

		self.server._handle_command = slow_handle

		# 1. Send slow command with timeout=0.1s
		with self.assertRaises(TimeoutError):
			self.client.send_command({"type": "slow_cmd"}, timeout=0.1)

		# 2. Wait for server to finish slow command and write its delayed response
		time.sleep(0.5)

		# 3. Send fast command on the same client connection.
		# Subsequent communication must not return the stale response from the timed-out command!
		resp2 = self.client.send_command({"type": "fast_status"}, timeout=2.0)
		self.assertEqual(
			resp2.get("type"),
			"fast_status_resp",
			f"Pipe framing corrupted after timeout! Expected 'fast_status_resp', but received stale frame: {resp2}",
		)

	def test_timeout_in_one_thread_poisons_subsequent_thread_response(self) -> None:
		"""Empirical challenge: verify that when Thread 1 times out, Thread 2 does not receive Thread 1's response."""
		server_received = threading.Event()

		def handle_cmd(frame: dict) -> None:
			if frame.get("type") == "thread1_slow":
				server_received.set()
				time.sleep(0.4)
				if self.server._cmd_server and self.server._cmd_server.is_connected:
					self.server._cmd_server.write_frame({"type": "thread1_resp", "owner": 1})
				return
			if frame.get("type") == "thread2_fast":
				if self.server._cmd_server and self.server._cmd_server.is_connected:
					self.server._cmd_server.write_frame({"type": "thread2_resp", "owner": 2})
				return

		self.server._handle_command = handle_cmd

		# Thread 1 sends slow command and times out
		with self.assertRaises(TimeoutError):
			self.client.send_command({"type": "thread1_slow"}, timeout=0.1)

		# Allow server to complete Thread 1's command
		time.sleep(0.5)

		# Thread 2 submits fast command
		resp = self.client.send_command({"type": "thread2_fast"}, timeout=2.0)
		self.assertEqual(
			resp.get("owner"),
			2,
			f"Thread 2 received stale response belonging to Thread 1! Got: {resp}",
		)

	def test_multiple_consecutive_timeouts_recover_cleanly(self) -> None:
		"""Empirical challenge: verify multiple consecutive timeouts do not break pipe recovery."""
		def handle_cmd(frame: dict) -> None:
			if frame.get("type") == "slow_cmd":
				time.sleep(0.3)
				if self.server._cmd_server and self.server._cmd_server.is_connected:
					self.server._cmd_server.write_frame({"type": "slow_resp"})
				return
			if frame.get("type") == "fast_cmd":
				if self.server._cmd_server and self.server._cmd_server.is_connected:
					self.server._cmd_server.write_frame({"type": "fast_resp", "seq": frame.get("seq")})
				return

		self.server._handle_command = handle_cmd

		# Execute 3 consecutive timed-out commands
		for i in range(3):
			with self.assertRaises(TimeoutError):
				self.client.send_command({"type": "slow_cmd"}, timeout=0.08)
			time.sleep(0.35)

		# Now send a valid command with sufficient timeout
		resp = self.client.send_command({"type": "fast_cmd", "seq": 42}, timeout=2.0)
		self.assertEqual(resp.get("type"), "fast_resp")
		self.assertEqual(resp.get("seq"), 42)

	def test_immediate_command_while_server_executing_timed_out_command(self) -> None:
		"""Empirical challenge: verify immediate follow-up command without sleep reconnects once server resets."""
		def handle_cmd(frame: dict) -> None:
			if frame.get("type") == "slow_cmd":
				time.sleep(0.35)
				if self.server._cmd_server and self.server._cmd_server.is_connected:
					self.server._cmd_server.write_frame({"type": "slow_resp"})
				return
			if frame.get("type") == "fast_cmd":
				if self.server._cmd_server and self.server._cmd_server.is_connected:
					self.server._cmd_server.write_frame({"type": "fast_resp", "seq": frame.get("seq")})
				return

		self.server._handle_command = handle_cmd

		# 1. Send slow command with 0.08s timeout
		with self.assertRaises(TimeoutError):
			self.client.send_command({"type": "slow_cmd"}, timeout=0.08)

		# 2. IMMEDIATELY send fast command without waiting for slow_cmd to finish
		resp = self.client.send_command({"type": "fast_cmd", "seq": 99}, timeout=3.0)
		self.assertEqual(resp.get("type"), "fast_resp")
		self.assertEqual(resp.get("seq"), 99)

	def test_poll_health_recovers_cleanly_after_command_timeout(self) -> None:
		"""Empirical challenge: verify poll_health automatically reconnects after a timed-out command."""
		def handle_cmd(frame: dict) -> None:
			if frame.get("type") == "slow_cmd":
				time.sleep(0.3)
				if self.server._cmd_server and self.server._cmd_server.is_connected:
					self.server._cmd_server.write_frame({"type": "slow_resp"})
				return
			# Default handler for worker_health_ping
			server_mod.WorkerServer._handle_command(self.server, frame)

		self.server._handle_command = handle_cmd

		with self.assertRaises(TimeoutError):
			self.client.send_command({"type": "slow_cmd"}, timeout=0.08)

		time.sleep(0.35)

		# poll_health uses its own cmd_lock branch with _needs_cmd_reconnect
		health = self.client.poll_health()
		self.assertTrue(health.is_healthy)
		self.assertGreater(health.worker_pid, 0)



class TestServerCrashAndBrokenPipe(unittest.TestCase):
	"""Test broken pipe detection and recovery when worker server dies."""

	def test_broken_pipe_raises_immediately(self) -> None:
		token = uuid.uuid4().hex[:8]
		cmd_pipe = f"\\\\.\\pipe\\chal_broken_cmd_{token}"
		evt_pipe = f"\\\\.\\pipe\\chal_broken_evt_{token}"
		server = WorkerServer(cmd_pipe_name=cmd_pipe, evt_pipe_name=evt_pipe)
		server.start()

		client = NamedPipeWorkerClient(cmd_pipe_name=cmd_pipe, evt_pipe_name=evt_pipe)
		client.connect()

		# Abruptly kill server
		server.shutdown()

		# Calling send_command should raise PipeDisconnectedError or OSError promptly
		start = time.perf_counter()
		with self.assertRaises((PipeDisconnectedError, OSError, RuntimeError)):
			client.send_command({"type": "litert_get_status"}, timeout=1.0)
		elapsed = time.perf_counter() - start
		self.assertLess(elapsed, 0.5)

		client.disconnect()

	def test_clean_pipe_recovery_after_worker_recycle(self) -> None:
		"""Broken pipe during shutdown can be cleanly recovered after worker recycle."""
		token = uuid.uuid4().hex[:8]
		cmd_pipe = f"\\\\.\\pipe\\chal_recycle_cmd_{token}"
		evt_pipe = f"\\\\.\\pipe\\chal_recycle_evt_{token}"

		server1 = WorkerServer(cmd_pipe_name=cmd_pipe, evt_pipe_name=evt_pipe)
		server1.start()

		client = NamedPipeWorkerClient(cmd_pipe_name=cmd_pipe, evt_pipe_name=evt_pipe)
		client.connect()
		supervisor = LiteRTServerSupervisor(worker_client=client)

		resp1 = client.send_command({"type": "litert_get_status", "command": "litert_get_status"})
		self.assertTrue(resp1.get("success"))

		# Abrupt server termination (worker process death)
		server1.shutdown()

		# Querying supervisor status during broken pipe must return idle without raising or hanging
		st_dead = supervisor.status()
		self.assertEqual(st_dead.state, "stopped")

		# Direct send_command must raise broken pipe promptly (< 0.5s)
		with self.assertRaises((PipeDisconnectedError, OSError, RuntimeError)):
			client.send_command({"type": "litert_get_status"}, timeout=1.0)

		# Disconnect stale client handles
		client.disconnect()

		# Start replacement worker server (worker restart / recycle)
		server2 = WorkerServer(cmd_pipe_name=cmd_pipe, evt_pipe_name=evt_pipe)
		server2.start()

		try:
			# Reconnect client to recycled server
			client.connect()
			resp2 = client.send_command({"type": "litert_get_status", "command": "litert_get_status"})
			self.assertTrue(resp2.get("success"))

			# Supervisor recovers cleanly without deadlocks or leaked locks
			st_recovered = supervisor.status()
			self.assertEqual(st_recovered.state, "stopped")
		finally:
			client.disconnect()
			server2.shutdown()

	def test_status_during_broken_pipe_never_hangs_or_crashes(self) -> None:
		"""LiteRTServerSupervisor.status() returns idle status non-blockingly when pipe breaks."""
		token = uuid.uuid4().hex[:8]
		cmd_pipe = f"\\\\.\\pipe\\chal_status_break_cmd_{token}"
		evt_pipe = f"\\\\.\\pipe\\chal_status_break_evt_{token}"

		server = WorkerServer(cmd_pipe_name=cmd_pipe, evt_pipe_name=evt_pipe)
		server.start()

		client = NamedPipeWorkerClient(cmd_pipe_name=cmd_pipe, evt_pipe_name=evt_pipe)
		client.connect()
		supervisor = LiteRTServerSupervisor(worker_client=client)

		server.shutdown()

		# Query status multiple times; verify each finishes < 50ms and returns stopped
		for _ in range(5):
			t0 = time.perf_counter()
			st = supervisor.status()
			elapsed = time.perf_counter() - t0
			self.assertEqual(st.state, "stopped")
			self.assertLess(elapsed, 0.1)

		client.disconnect()


class TestProcessCrashContainmentAndTypeSafety(unittest.TestCase):
	"""Adversarially challenge process crash containment, generation fencing, and attribute type safety."""

	def test_process_termination_containment_and_diagnostics(self) -> None:
		"""If supervised child process terminates abruptly, worker captures it, increments generation, and reports failed."""
		try:
			from runtime_supervisor import RuntimeSupervisor
		except ImportError:
			self.skipTest("runtime_supervisor native module not available")

		token = uuid.uuid4().hex[:8]
		cmd_pipe = f"\\\\.\\pipe\\chal_proc_crash_cmd_{token}"
		evt_pipe = f"\\\\.\\pipe\\chal_proc_crash_evt_{token}"

		server = WorkerServer(cmd_pipe_name=cmd_pipe, evt_pipe_name=evt_pipe)
		executor = LiteRTWorkerExecutor(port=9398)

		# Native supervisor instance
		sup = RuntimeSupervisor("litert-lm", "127.0.0.1", 9398)
		# Trigger abrupt process exit with exit code 42
		with self.assertRaises(RuntimeError):
			sup.ensure_ready(
				sys.executable,
				["-c", "import sys; sys.exit(42)"],
				{},
				"crash-ident",
				timeout_seconds=2.0,
			)

		executor._supervisor = sup
		server._litert_executor = executor
		server.start()

		client = NamedPipeWorkerClient(cmd_pipe_name=cmd_pipe, evt_pipe_name=evt_pipe)
		client.connect()
		supervisor = LiteRTServerSupervisor(worker_client=client)

		try:
			# Non-blocking status query across IPC
			t0 = time.perf_counter()
			status = supervisor.status()
			elapsed = time.perf_counter() - t0

			self.assertLess(elapsed, 0.5, "status() took too long")
			self.assertEqual(status.state, "failed")
			self.assertFalse(status.is_ready)
			self.assertFalse(status.is_running)
			self.assertGreaterEqual(status.generation, 1)
			self.assertIsNotNone(status.error_message)
			self.assertIn("42", status.error_message)
		finally:
			client.disconnect()
			server.shutdown()

	def test_is_connected_attribute_vs_method_type_safety(self) -> None:
		"""Verify that boolean, property, and callable is_connected variations never raise TypeError."""
		class PropClientTrue:
			@property
			def is_connected(self) -> bool:
				return True

			def send_command(self, cmd: dict, timeout: float = 10.0) -> dict:
				return {"success": True, "status": {"state": "ready", "generation": 1, "is_ready": True}, "models": ["m1"]}

		class PropClientFalse:
			@property
			def is_connected(self) -> bool:
				return False

		class MethodClientTrue:
			def is_connected(self) -> bool:
				return True

			def send_command(self, cmd: dict, timeout: float = 10.0) -> dict:
				return {"success": True, "status": {"state": "ready", "generation": 1, "is_ready": True}, "models": ["m1"]}

		class MethodClientFalse:
			def is_connected(self) -> bool:
				return False

		class AttrClientTrue:
			def __init__(self) -> None:
				self.is_connected = True

			def send_command(self, cmd: dict, timeout: float = 10.0) -> dict:
				return {"success": True, "status": {"state": "ready", "generation": 1, "is_ready": True}, "models": ["m1"]}

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
				sup = LiteRTServerSupervisor(worker_client=client)

				# Test _get_worker_client()
				resolved = sup._get_worker_client()
				if expected_connected:
					self.assertIs(resolved, client)
				else:
					self.assertIsNone(resolved)

				# Test status() - MUST never raise TypeError
				st = sup.status()
				if expected_connected:
					self.assertEqual(st.state, "ready")
					self.assertTrue(st.is_ready)
				else:
					self.assertEqual(st.state, "stopped")
					self.assertFalse(st.is_ready)

				# Test ensure_ready() and stop()
				if expected_connected:
					ready_st = sup.ensure_ready()
					self.assertEqual(ready_st.state, "ready")
					stop_st = sup.stop()
					self.assertEqual(stop_st.state, "ready")
				else:
					with self.assertRaises(LiteRTServerError):
						sup.ensure_ready()
					idle_st = sup.stop()
					self.assertEqual(idle_st.state, "stopped")


if __name__ == "__main__":
	unittest.main()

