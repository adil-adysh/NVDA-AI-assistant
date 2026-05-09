# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
	sys.path.insert(0, str(MODULE_DIR))

ui_actions = importlib.import_module("ui_actions")

ConversationDeleteAction = ui_actions.ConversationDeleteAction
ConversationNewAction = ui_actions.ConversationNewAction
ConversationOpenAction = ui_actions.ConversationOpenAction
OpenChatAction = ui_actions.OpenChatAction
parse_ui_action = ui_actions.parse_ui_action
serialize_ui_action = ui_actions.serialize_ui_action


class UIActionTests(unittest.TestCase):
	def test_parse_conversation_new_action(self) -> None:
		action = parse_ui_action("conversation_new", None)

		self.assertIsInstance(action, ConversationNewAction)

	def test_parse_conversation_open_requires_conversation_id(self) -> None:
		action = parse_ui_action("conversation_open", {"conversation_id": "   "})

		self.assertIsNone(action)

	def test_parse_conversation_open_action(self) -> None:
		action = parse_ui_action("conversation_open", {"conversation_id": "conv-123"})

		self.assertEqual(action, ConversationOpenAction(conversation_id="conv-123"))

	def test_parse_conversation_delete_action(self) -> None:
		action = parse_ui_action("conversation_delete", {"conversation_id": "conv-456"})

		self.assertEqual(action, ConversationDeleteAction(conversation_id="conv-456"))

	def test_open_chat_roundtrip_preserves_payload(self) -> None:
		serialized_id, serialized_payload = serialize_ui_action(
			OpenChatAction(
				token="token-1",
				assistant_seed_text="Summarize this",
				initial_image_base64="abc123",
				force_new_conversation=True,
			)
		)

		parsed = parse_ui_action(serialized_id, serialized_payload)

		self.assertEqual(
			parsed,
			OpenChatAction(
				token="token-1",
				assistant_seed_text="Summarize this",
				initial_image_base64="abc123",
				force_new_conversation=True,
			),
		)

	def test_serialize_conversation_open_action(self) -> None:
		action_id, payload = serialize_ui_action(ConversationOpenAction(conversation_id="conv-789"))

		self.assertEqual(action_id, "conversation_open")
		self.assertEqual(payload, {"conversation_id": "conv-789"})

	def test_parse_unknown_action_returns_none(self) -> None:
		action = parse_ui_action("unknown_action", {"anything": "value"})

		self.assertIsNone(action)


if __name__ == "__main__":
	unittest.main()
