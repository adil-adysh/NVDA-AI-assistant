# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
	sys.path.insert(0, str(MODULE_DIR))

from host_protocol import (  # type: ignore[import-not-found]
	ACK_TYPE,
	COMMAND_TYPE,
	PROTOCOL_VERSION,
	SCHEMA,
	HostCommand,
	HostResponse,
)


class HostProtocolTests(unittest.TestCase):
	def test_host_command_roundtrip(self) -> None:
		command = HostCommand(name="render_display", payload={"output_text": "Hello"})
		payload = command.to_json()
		parsed = HostCommand.from_json(payload)

		self.assertEqual(parsed.name, "render_display")
		self.assertEqual(parsed.id, command.id)
		self.assertEqual(parsed.type, COMMAND_TYPE)
		self.assertEqual(parsed.protocol_version, PROTOCOL_VERSION)
		self.assertEqual(parsed.payload["output_text"], "Hello")

	def test_host_command_rejects_unsupported_protocol_version(self) -> None:
		payload = json.dumps(
			{
				"schema": SCHEMA,
				"type": COMMAND_TYPE,
				"id": "test-id",
				"version": 999,
				"source": "nvda_addon",
				"command": {"name": "render_display", "payload": {}},
			}
		)

		with self.assertRaises(ValueError):
			HostCommand.from_json(payload)

	def test_host_response_roundtrip(self) -> None:
		response = HostResponse(request_id="test-id", status="ack", message="ok", stage="enqueued")
		payload = response.to_json()
		parsed = HostResponse.from_json(payload)

		self.assertEqual(parsed.request_id, "test-id")
		self.assertEqual(parsed.status, "ack")
		self.assertEqual(parsed.type, ACK_TYPE)
		self.assertEqual(parsed.message, "ok")
		self.assertEqual(parsed.stage, "enqueued")

	def test_host_response_rejects_invalid_status(self) -> None:
		payload = json.dumps(
			{
				"schema": SCHEMA,
				"version": PROTOCOL_VERSION,
				"id": "resp-1",
				"correlation_id": "test-id",
				"source": "ui_host",
				"type": "mystery",
			}
		)

		with self.assertRaises(ValueError):
			HostResponse.from_json(payload)


if __name__ == "__main__":
	unittest.main()
