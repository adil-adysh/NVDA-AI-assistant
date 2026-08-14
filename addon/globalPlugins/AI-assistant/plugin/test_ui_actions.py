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

AddItemToChatAction = ui_actions.AddItemToChatAction
ConversationDeleteAction = ui_actions.ConversationDeleteAction
ConversationNewAction = ui_actions.ConversationNewAction
ConversationOpenAction = ui_actions.ConversationOpenAction
OpenInNewChatAction = ui_actions.OpenInNewChatAction
NavigateToTargetAction = ui_actions.NavigateToTargetAction
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

	def test_add_item_roundtrip_preserves_token_and_item_id(self) -> None:
		serialized_id, serialized_payload = serialize_ui_action(
			AddItemToChatAction(token="token-1", item_id="page_content")
		)

		self.assertEqual(serialized_id, "add_page_content_to_chat")
		self.assertEqual(serialized_payload, {"token": "token-1"})

		parsed = parse_ui_action(serialized_id, serialized_payload)

		self.assertEqual(
			parsed,
			AddItemToChatAction(token="token-1", item_id="page_content"),
		)

	def test_parse_add_item_requires_token(self) -> None:
		action = parse_ui_action("add_summary_to_chat", {"item_id": "summary"})

		self.assertIsNone(action)

	def test_parse_add_item_requires_non_empty_item_id(self) -> None:
		action = parse_ui_action("add__to_chat", {"token": "token-1"})

		self.assertIsNone(action)

	def test_open_in_new_chat_roundtrip_preserves_token(self) -> None:
		serialized_id, serialized_payload = serialize_ui_action(
			OpenInNewChatAction(token="token-2")
		)

		self.assertEqual(serialized_id, "open_in_new_chat")
		self.assertEqual(serialized_payload, {"token": "token-2"})

		parsed = parse_ui_action(serialized_id, serialized_payload)

		self.assertEqual(parsed, OpenInNewChatAction(token="token-2"))

	def test_parse_open_in_new_chat_requires_token(self) -> None:
		action = parse_ui_action("open_in_new_chat", {})

		self.assertIsNone(action)

	def test_navigation_target_roundtrip_preserves_token_and_target(self) -> None:
		serialized_id, serialized_payload = serialize_ui_action(
			NavigateToTargetAction(token="token-3", target_id="nav-abc")
		)

		self.assertEqual(serialized_id, "navigate_to_target")
		self.assertEqual(serialized_payload, {"token": "token-3", "target_id": "nav-abc"})
		self.assertEqual(
			parse_ui_action(serialized_id, serialized_payload),
			NavigateToTargetAction(token="token-3", target_id="nav-abc"),
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
