# -*- coding: utf-8 -*-
# Pylint cannot infer attributes assigned to types.ModuleType() fakes used
# to stub NVDA-internal modules (E1101 ``__name__`` false positives).
# Tests intentionally inspect coordinator internals (W0212) and deliberately
# duplicate the self-contained synthetic-package bootstrap (R0801).
# pylint: disable=no-member,protected-access,duplicate-code
from __future__ import annotations

import sys
import types
import unittest

from tests.support import ADDON_ROOT, load_module as _load_module, register_package as _register_package


ROOT_DIR = ADDON_ROOT
MODULE_DIR = ROOT_DIR / "service" / "chat"
PACKAGE_NAME = "chat_coordinator_testpkg"


class _FakeBaseCoordinator:
	def __init__(self, metrics_reporter=None, ui_port=None) -> None:
		self.metrics_reporter = metrics_reporter
		self.ui_port = ui_port


class _FakeProviderLLMService:
	pass


class _FakeProviderModelInfo:
	pass


class _FakeMetricsReporter:
	pass


class _FakeRepository:
	def __init__(self) -> None:
		self.saved: dict[str, list[object]] = {}
		self.deleted_ids: list[str] = []

	def exists(self, conversation_id: str) -> bool:
		return conversation_id in self.saved

	def load(self, conversation_id: str):
		session = session_module.ConversationSession()
		session.extend(self.saved.get(conversation_id, []))
		return session

	def save(self, conversation_id: str, messages) -> None:
		self.saved[conversation_id] = list(messages)

	def list_summaries(self):
		return []

	def delete(self, conversation_id: str) -> bool:
		self.deleted_ids.append(conversation_id)
		return self.saved.pop(conversation_id, None) is not None


def _build_user_message(*args, **kwargs):
	raise AssertionError("build_user_message should not be used in this test")


def _message_to_chat_message(message):
	return message


def _no_op(*_args, **_kwargs):
	return None


_register_package(PACKAGE_NAME, ROOT_DIR)
_register_package(f"{PACKAGE_NAME}.core", ROOT_DIR / "core")
_register_package(f"{PACKAGE_NAME}.observability", ROOT_DIR / "observability")
_register_package(f"{PACKAGE_NAME}.providers", ROOT_DIR / "providers")
_register_package(f"{PACKAGE_NAME}.service", ROOT_DIR / "service")
_register_package(f"{PACKAGE_NAME}.service.chat", MODULE_DIR)

base_module = types.ModuleType(f"{PACKAGE_NAME}.service.base")
base_module.BaseCoordinator = _FakeBaseCoordinator
sys.modules[base_module.__name__] = base_module

events_module = types.ModuleType(f"{PACKAGE_NAME}.core.events")
events_module.ProgressHandler = object
sys.modules[events_module.__name__] = events_module

llm_module = types.ModuleType(f"{PACKAGE_NAME}.service.llm")
llm_module.ProviderLLMService = _FakeProviderLLMService
sys.modules[llm_module.__name__] = llm_module

provider_interfaces_module = types.ModuleType(f"{PACKAGE_NAME}.providers.interfaces")
provider_interfaces_module.ProviderModelInfo = _FakeProviderModelInfo
sys.modules[provider_interfaces_module.__name__] = provider_interfaces_module

metrics_module = types.ModuleType(f"{PACKAGE_NAME}.observability.reporter")
metrics_module.MetricsReporter = _FakeMetricsReporter
sys.modules[metrics_module.__name__] = metrics_module

repository_module = types.ModuleType(f"{PACKAGE_NAME}.service.chat.repository")
repository_module.ConversationRepository = _FakeRepository
repository_module.ConversationSummary = object
sys.modules[repository_module.__name__] = repository_module

transaction_module = types.ModuleType(f"{PACKAGE_NAME}.service.chat.transaction")
transaction_module.ChatTurnTransaction = object
sys.modules[transaction_module.__name__] = transaction_module

_load_module(f"{PACKAGE_NAME}.core.canonical", ROOT_DIR / "core" / "canonical.py")
message_transforms_module = types.ModuleType(f"{PACKAGE_NAME}.core.message_transforms")
message_transforms_module.build_user_message = _build_user_message
message_transforms_module.message_to_chat_message = _message_to_chat_message
sys.modules[message_transforms_module.__name__] = message_transforms_module

messages_module = types.ModuleType(f"{PACKAGE_NAME}.core.messages")
messages_module.ChatMessage = object
messages_module.LLMResponse = object
sys.modules[messages_module.__name__] = messages_module

projector_module = types.ModuleType(f"{PACKAGE_NAME}.service.chat.projector")
projector_module.project_chat_history = list
projector_module.project_chat_history_transport = list
sys.modules[projector_module.__name__] = projector_module

session_module = _load_module(f"{PACKAGE_NAME}.service.chat.session", MODULE_DIR / "session.py")
coordinator_module = _load_module(f"{PACKAGE_NAME}.service.chat.coordinator", MODULE_DIR / "coordinator.py")

ChatCoordinator = coordinator_module.ChatCoordinator


class ChatCoordinatorTests(unittest.TestCase):
	def test_activate_conversation_does_not_persist_empty_session(self) -> None:
		repository = _FakeRepository()
		coordinator = ChatCoordinator(client=_FakeProviderLLMService(), repository=repository)

		conversation_id = coordinator.activate_conversation(conversation_id="conv-empty")

		self.assertEqual(conversation_id, "conv-empty")
		self.assertEqual(repository.saved, {})
		self.assertEqual(repository.deleted_ids, ["conv-empty"])

	def test_reset_deletes_persisted_conversation_when_session_becomes_empty(self) -> None:
		repository = _FakeRepository()
		coordinator = ChatCoordinator(client=_FakeProviderLLMService(), repository=repository)
		conversation_id = coordinator.activate_conversation(conversation_id="conv-reset")
		repository.save(conversation_id, [object()])
		coordinator._session.extend([object()])

		coordinator.reset()

		self.assertNotIn(conversation_id, repository.saved)
		self.assertEqual(repository.deleted_ids[-1], conversation_id)

	def test_switching_to_new_conversation_archives_previous_active_conversation(self) -> None:
		repository = _FakeRepository()
		coordinator = ChatCoordinator(client=_FakeProviderLLMService(), repository=repository)
		coordinator.activate_conversation(conversation_id="conv-current")
		coordinator._session.extend([object()])

		new_conversation_id = coordinator.activate_conversation(conversation_id="conv-next")

		self.assertEqual(new_conversation_id, "conv-next")
		self.assertEqual(len(repository.saved["conv-current"]), 1)
		self.assertEqual(repository.deleted_ids, ["conv-current", "conv-next"])


if __name__ == "__main__":
	unittest.main()
