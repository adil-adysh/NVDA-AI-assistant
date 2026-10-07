# -*- coding: utf-8 -*-
"""Unit tests for Named Pipe Transport, NDJSON Framing, and Broken-Pipe Latency (Invariant A18)."""

from __future__ import annotations

import threading
import time
import unittest
import uuid

from tests.support import load_addon_module

trans_mod = load_addon_module("worker.ipc.transport")
sec_mod = load_addon_module("worker.ipc.security")

NamedPipeClient = trans_mod.NamedPipeClient
NamedPipeServer = trans_mod.NamedPipeServer
PipeDisconnectedError = trans_mod.PipeDisconnectedError
build_user_only_security_attributes = sec_mod.build_user_only_security_attributes
get_current_user_sid_str = sec_mod.get_current_user_sid_str


class TestPipeTransport(unittest.TestCase):
	"""Verify NamedPipeServer and NamedPipeClient communication and failure detection."""

	def _make_pipe_name(self) -> str:
		return f"\\\\.\\pipe\\nvda_ai_test_pipe_{uuid.uuid4().hex[:8]}"

	def test_security_dacl_builder(self) -> None:
		"""Verify Win32 DACL is constructed for current user SID."""
		sid = get_current_user_sid_str()
		self.assertTrue(sid.startswith("S-1-5-"))
		sa = build_user_only_security_attributes()
		self.assertIsNotNone(sa)

	def test_named_pipe_roundtrip(self) -> None:
		"""Verify bidirectional exchange of NDJSON frames over named pipes."""
		pipe_name = self._make_pipe_name()
		server = NamedPipeServer(pipe_name)
		client = NamedPipeClient(pipe_name)

		def run_client() -> None:
			client.connect(timeout_seconds=2.0)
			client.write_frame({"greeting": "hello from client"})
			resp = client.read_frame()
			self.assertEqual(resp.get("greeting"), "hello from server")
			client.close()

		client_thread = threading.Thread(target=run_client)
		client_thread.start()

		connected = server.accept_connection(timeout_seconds=2.0)
		self.assertTrue(connected)

		req = server.read_frame()
		self.assertEqual(req.get("greeting"), "hello from client")
		server.write_frame({"greeting": "hello from server"})

		client_thread.join(timeout=2.0)
		server.close()
		self.assertFalse(client_thread.is_alive())

	def test_rapid_multiple_frames(self) -> None:
		"""Verify buffer handling when multiple NDJSON frames arrive simultaneously."""
		pipe_name = self._make_pipe_name()
		server = NamedPipeServer(pipe_name)
		client = NamedPipeClient(pipe_name)

		def run_client() -> None:
			client.connect(timeout_seconds=2.0)
			for i in range(10):
				client.write_frame({"index": i, "data": "x" * 100})
			client.close()

		client_thread = threading.Thread(target=run_client)
		client_thread.start()

		self.assertTrue(server.accept_connection(timeout_seconds=2.0))
		received_indices: list[int] = []
		for _ in range(10):
			frame = server.read_frame()
			received_indices.append(int(frame["index"]))

		self.assertEqual(received_indices, list(range(10)))
		client_thread.join(timeout=2.0)
		server.close()

	def test_broken_pipe_detection_under_5ms(self) -> None:
		"""Verify broken-pipe detection occurs in under 5 milliseconds (Invariant A19)."""
		pipe_name = self._make_pipe_name()
		server = NamedPipeServer(pipe_name)
		client = NamedPipeClient(pipe_name)

		t_close = [0.0]

		def client_closer() -> None:
			client.connect(timeout_seconds=2.0)
			time.sleep(0.05)
			t_close[0] = time.perf_counter()
			client.close()  # Peer abruptly closes connection

		client_thread = threading.Thread(target=client_closer)
		client_thread.start()

		self.assertTrue(server.accept_connection(timeout_seconds=2.0))

		with self.assertRaises(PipeDisconnectedError):
			server.read_frame()

		t_unblock = time.perf_counter()
		latency_ms = (t_unblock - t_close[0]) * 1000.0

		client_thread.join(timeout=2.0)
		server.close()

		self.assertLess(
			latency_ms,
			5.0,
			f"Broken pipe detection latency {latency_ms:.3f}ms exceeded 5.0ms threshold",
		)

	def test_client_connect_timeout(self) -> None:
		"""Verify client raises TimeoutError if pipe does not exist within timeout."""
		non_existent_pipe = (
			f"\\\\.\\pipe\\non_existent_{uuid.uuid4().hex[:8]}"
		)
		client = NamedPipeClient(non_existent_pipe)
		t0 = time.monotonic()
		with self.assertRaises(TimeoutError):
			client.connect(timeout_seconds=0.2)
		elapsed = time.monotonic() - t0
		self.assertGreaterEqual(elapsed, 0.15)


if __name__ == "__main__":
	unittest.main()
