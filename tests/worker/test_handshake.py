# -*- coding: utf-8 -*-
"""Unit tests for Protocol Handshake and Capability Negotiation (Invariant A17)."""

from __future__ import annotations

import unittest
import uuid

from tests.support import load_addon_module

dto_mod = load_addon_module("core.job.dto")
proto_mod = load_addon_module("core.job.protocol")
server_mod = load_addon_module("worker.server")
trans_mod = load_addon_module("worker.ipc.transport")

HandshakeRequest = dto_mod.HandshakeRequest
HandshakeResponse = dto_mod.HandshakeResponse
NamedPipeClient = trans_mod.NamedPipeClient
WorkerServer = server_mod.WorkerServer


class TestProtocolHandshake(unittest.TestCase):
	"""Verify versioned handshake exchange and capability negotiation across named pipes."""

	def setUp(self) -> None:
		token = uuid.uuid4().hex[:8]
		self.cmd_pipe = f"\\\\.\\pipe\\test_handshake_cmd_{token}"
		self.evt_pipe = f"\\\\.\\pipe\\test_handshake_evt_{token}"
		self.server = WorkerServer(
			cmd_pipe_name=self.cmd_pipe,
			evt_pipe_name=self.evt_pipe,
		)
		self.server.start()
		self.client = NamedPipeClient(self.cmd_pipe)
		self.client.connect(timeout_seconds=2.0)

	def tearDown(self) -> None:
		self.client.close()
		self.server.shutdown()

	def test_compatible_handshake_accepted(self) -> None:
		"""Verify client with identical major version (1.0.0) is accepted."""
		req = HandshakeRequest(
			protocol_version="1.0.0",
			client_name="test_client",
			client_version="1.0.0",
			requested_capabilities=("job.echo", "job.trivial_compute"),
		)
		self.client.write_frame(req.to_dict())
		raw_resp = self.client.read_frame()

		resp = HandshakeResponse.from_dict(raw_resp)
		self.assertTrue(resp.accepted)
		self.assertEqual(resp.protocol_version, "1.0.0")
		self.assertEqual(resp.correlation_id, req.request_id)
		self.assertIn("job.echo", resp.negotiated_capabilities)
		self.assertIn("job.trivial_compute", resp.negotiated_capabilities)

	def test_incompatible_major_version_rejected(self) -> None:
		"""Verify client with breaking major version (2.0.0) is rejected."""
		req = HandshakeRequest(
			protocol_version="2.0.0",
			client_name="future_client",
			client_version="2.0.0",
		)
		self.client.write_frame(req.to_dict())
		raw_resp = self.client.read_frame()

		resp = HandshakeResponse.from_dict(raw_resp)
		self.assertFalse(resp.accepted)
		self.assertIsNotNone(resp.error_message)
		self.assertIn("Incompatible protocol version", str(resp.error_message))
		self.assertEqual(resp.negotiated_capabilities, ())

	def test_capability_subset_negotiation(self) -> None:
		"""Verify worker negotiates only supported capabilities."""
		req = HandshakeRequest(
			protocol_version="1.0.0",
			requested_capabilities=(
				"job.echo",
				"unknown.quantum_teleportation",
			),
		)
		self.client.write_frame(req.to_dict())
		raw_resp = self.client.read_frame()

		resp = HandshakeResponse.from_dict(raw_resp)
		self.assertTrue(resp.accepted)
		self.assertIn("job.echo", resp.negotiated_capabilities)
		self.assertNotIn(
			"unknown.quantum_teleportation", resp.negotiated_capabilities
		)


if __name__ == "__main__":
	unittest.main()
