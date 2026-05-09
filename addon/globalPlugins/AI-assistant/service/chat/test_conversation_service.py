# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import sys
import types
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent
ROOT_DIR = MODULE_DIR.parent.parent
PACKAGE_NAME = "conversation_service_testpkg"


def _register_package(name: str, path: Path | None = None) -> types.ModuleType:
	module = types.ModuleType(name)
	if path is not None:
		module.__path__ = [str(path)]
	sys.modules[name] = module
	return module


def _load_module(module_name: str, file_path: Path):
	spec = importlib.util.spec_from_file_location(module_name, file_path)
	if spec is None or spec.loader is None:
		raise RuntimeError(f"Unable to load {module_name}")
	module = importlib.util.module_from_spec(spec)
	sys.modules[module_name] = module
	spec.loader.exec_module(module)
	return module


class _StubChatCoordinator:
	pass


@dataclass(frozen=True)
class _Summary:
	conversation_id: str
	title: str
	preview: str
	message_count: int
	updated_at: float

	def to_metadata(self) -> dict[str, object]:
		return {
			"id": self.conversation_id,
			"title": self.title,
			"preview": self.preview,
			"message_count": self.message_count,
			"updated_at": self.updated_at,
		}


class _FakeCoordinator:
	def __init__(self) -> None:
		self.active_conversation_id: str | None = "conv-active"
		self.delete_result = False
		self.history = [{"id": "history-1", "role": "user", "content": [{"type": "text", "text": "hello"}]}]
		self.summaries = [_Summary("conv-1", "First", "Preview", 2, 123.0)]
		self.activate_calls: list[dict[str, object]] = []
		self.deleted_ids: list[str] = []

	def activate_conversation(self, *, conversation_id: str | None = None, seed_messages=()):
		self.activate_calls.append({"conversation_id": conversation_id, "seed_messages": tuple(seed_messages)})
		self.active_conversation_id = conversation_id or "generated-conv"
		return self.active_conversation_id

	def get_active_conversation_id(self) -> str | None:
		return self.active_conversation_id

	def get_history_transport(self) -> list[dict[str, object]]:
		return list(self.history)

	def list_conversations(self):
		return list(self.summaries)

	def delete_conversation(self, conversation_id: str) -> bool:
		self.deleted_ids.append(conversation_id)
		if self.delete_result and conversation_id == self.active_conversation_id:
			self.active_conversation_id = None
		return self.delete_result


_register_package(PACKAGE_NAME, ROOT_DIR)
_register_package(f"{PACKAGE_NAME}.core", ROOT_DIR / "core")
_register_package(f"{PACKAGE_NAME}.service", ROOT_DIR / "service")
_register_package(f"{PACKAGE_NAME}.service.chat", MODULE_DIR)

coordinator_module = types.ModuleType(f"{PACKAGE_NAME}.service.chat.coordinator")
coordinator_module.ChatCoordinator = _StubChatCoordinator
sys.modules[coordinator_module.__name__] = coordinator_module

_load_module(f"{PACKAGE_NAME}.core.canonical", ROOT_DIR / "core" / "canonical.py")
_load_module(f"{PACKAGE_NAME}.core.messages", ROOT_DIR / "core" / "messages.py")
_load_module(f"{PACKAGE_NAME}.core.tooling", ROOT_DIR / "core" / "tooling.py")
_load_module(f"{PACKAGE_NAME}.core.message_transforms", ROOT_DIR / "core" / "message_transforms.py")
conversation_service_module = _load_module(
	f"{PACKAGE_NAME}.service.chat.conversation_service",
	MODULE_DIR / "conversation_service.py",
)

ConversationDeleteResult = conversation_service_module.ConversationDeleteResult
ConversationService = conversation_service_module.ConversationService


class ConversationServiceTests(unittest.TestCase):
	def setUp(self) -> None:
		self.coordinator = _FakeCoordinator()
		self.service = ConversationService(self.coordinator)

	def test_open_conversation_builds_seed_message_for_assistant_text(self) -> None:
		conversation_id = self.service.open_conversation(
			conversation_id="conv-123",
			initial_assistant_text="  Saved reply  ",
		)

		self.assertEqual(conversation_id, "conv-123")
		self.assertEqual(len(self.coordinator.activate_calls), 1)
		activate_call = self.coordinator.activate_calls[0]
		self.assertEqual(activate_call["conversation_id"], "conv-123")
		seed_messages = activate_call["seed_messages"]
		self.assertEqual(len(seed_messages), 1)
		self.assertEqual(seed_messages[0].role, "assistant")
		self.assertEqual(seed_messages[0].parts[0].text, "Saved reply")

	def test_open_conversation_reuses_current_active_conversation_by_default(self) -> None:
		conversation_id = self.service.open_conversation()

		self.assertEqual(conversation_id, "conv-active")
		self.assertEqual(self.coordinator.activate_calls[0]["conversation_id"], "conv-active")

	def test_open_conversation_can_force_new_conversation(self) -> None:
		conversation_id = self.service.open_conversation(force_new=True)

		self.assertEqual(conversation_id, "generated-conv")
		self.assertIsNone(self.coordinator.activate_calls[0]["conversation_id"])

	def test_list_conversation_summaries_projects_metadata(self) -> None:
		summaries = self.service.list_conversation_summaries()

		self.assertEqual(
			summaries,
			[{"id": "conv-1", "title": "First", "preview": "Preview", "message_count": 2, "updated_at": 123.0}],
		)

	def test_delete_conversation_reports_active_delete(self) -> None:
		self.coordinator.active_conversation_id = "conv-1"
		self.coordinator.delete_result = True

		result = self.service.delete_conversation("conv-1")

		self.assertEqual(
			result,
			ConversationDeleteResult(
				deleted=True,
				active_conversation_deleted=True,
				active_conversation_id=None,
			),
		)

	def test_delete_conversation_reports_inactive_delete(self) -> None:
		self.coordinator.active_conversation_id = "conv-active"
		self.coordinator.delete_result = True

		result = self.service.delete_conversation("conv-2")

		self.assertEqual(
			result,
			ConversationDeleteResult(
				deleted=True,
				active_conversation_deleted=False,
				active_conversation_id="conv-active",
			),
		)


if __name__ == "__main__":
	unittest.main()
