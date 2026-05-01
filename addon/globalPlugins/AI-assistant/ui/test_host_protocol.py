# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import importlib
import sys
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
	sys.path.insert(0, str(MODULE_DIR))

host_protocol = importlib.import_module("host_protocol")
ACK_TYPE = host_protocol.ACK_TYPE
COMMAND_TYPE = host_protocol.COMMAND_TYPE
EVENT_CHAT_SUBMITTED = host_protocol.EVENT_CHAT_SUBMITTED
PROTOCOL_VERSION = host_protocol.PROTOCOL_VERSION
SCHEMA = host_protocol.SCHEMA
HostCommand = host_protocol.HostCommand
HostEvent = host_protocol.HostEvent
HostResponse = host_protocol.HostResponse


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

	def test_chat_set_history_command_roundtrip(self) -> None:
		history_payload = {
			"conversation_id": "abc",
			"messages": [
				{"id": "msg_1", "role": "user", "content": [{"type": "text", "text": "Hello"}], "timestamp": 1710000000}
			],
		}
		command = HostCommand(name="chat_set_history", payload=history_payload)
		payload = command.to_json()
		parsed = HostCommand.from_json(payload)

		self.assertEqual(parsed.name, "chat_set_history")
		self.assertEqual(parsed.payload["conversation_id"], "abc")
		self.assertEqual(parsed.payload["messages"][0]["role"], "user")

	def test_chat_stream_delta_command_roundtrip(self) -> None:
		command = HostCommand(
			name="chat_stream_delta",
			payload={
				"conversation_id": "abc",
				"message_id": "assistant_1",
				"delta": "Hello",
				"sequence": 3,
			},
		)
		payload = command.to_json()
		parsed = HostCommand.from_json(payload)

		self.assertEqual(parsed.name, "chat_stream_delta")
		self.assertEqual(parsed.payload["message_id"], "assistant_1")
		self.assertEqual(parsed.payload["delta"], "Hello")
		self.assertEqual(parsed.payload["sequence"], 3)

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

	def test_host_event_roundtrip(self) -> None:
		payload = {"conversation_id": "abc", "message": "Hello"}
		event = HostEvent(event=EVENT_CHAT_SUBMITTED, payload=payload, correlation_id="req-1")
		payload_json = event.to_json()
		parsed = HostEvent.from_json(payload_json)

		self.assertEqual(parsed.event, EVENT_CHAT_SUBMITTED)
		self.assertEqual(parsed.payload["message"], "Hello")
		self.assertEqual(parsed.correlation_id, "req-1")


if __name__ == "__main__":
	unittest.main()
