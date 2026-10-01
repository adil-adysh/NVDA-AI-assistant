"""Cross-component chat lifecycle tests with deterministically controlled providers."""

from __future__ import annotations

import importlib
import json
import threading

from tests.support import ADDON_ROOT, register_package


NAMESPACE = "chat_lifecycle_integration_testpkg"
register_package(NAMESPACE, ADDON_ROOT)

canonical = importlib.import_module(f"{NAMESPACE}.core.canonical")
messages = importlib.import_module(f"{NAMESPACE}.core.messages")
llm_module = importlib.import_module(f"{NAMESPACE}.service.llm")
coordinator_module = importlib.import_module(f"{NAMESPACE}.service.chat.coordinator")
repository_module = importlib.import_module(f"{NAMESPACE}.service.chat.repository_backends")
tooling = importlib.import_module(f"{NAMESPACE}.core.tooling")
tools_module = importlib.import_module(f"{NAMESPACE}.tools")

Message = canonical.Message
Part = canonical.Part
LLMResponse = messages.LLMResponse
ProviderLLMService = llm_module.ProviderLLMService
ChatCoordinator = coordinator_module.ChatCoordinator
JsonConversationRepository = repository_module.JsonConversationRepository
ToolCall = tooling.ToolCall
ToolExecutor = tools_module.ToolExecutor
ToolRegistry = tools_module.ToolRegistry


def _text(message: Message) -> str:
	return "".join(part.text or "" for part in message.parts if part.type == "text")


class ControlledProvider:
	"""Provider fake whose first response is released explicitly by the test."""

	def __init__(self) -> None:
		self.first_started = threading.Event()
		self.release_first = threading.Event()
		self.calls: list[list[Message]] = []
		self._lock = threading.Lock()

	def provider_name(self) -> str:
		return "controlled"

	def get_model_info(self, model_name=None):
		return None

	def generate(self, messages, tools=None, stream_handler=None):
		with self._lock:
			call_number = len(self.calls) + 1
			self.calls.append(list(messages))
		if call_number == 1:
			self.first_started.set()
			assert self.release_first.wait(5), "test did not release the first provider response"
		text = f"reply-{call_number}"
		if stream_handler is not None:
			stream_handler(text, len(text))
		return LLMResponse(text=text, model="controlled-model")


def test_rapid_submissions_are_serialized_and_second_turn_sees_first_history(monkeypatch, tmp_path) -> None:
	"""Rapid UI submissions must not generate from one stale transcript snapshot."""
	monkeypatch.setattr(llm_module, "is_streaming_enabled", lambda: True)
	provider = ControlledProvider()
	repository = JsonConversationRepository(tmp_path / "conversations.json")
	coordinator = ChatCoordinator(ProviderLLMService(provider), repository=repository)
	coordinator.activate_conversation("conversation")
	results: dict[str, str] = {}

	first = threading.Thread(
		target=lambda: results.setdefault("first", coordinator.send_message(text="first").text)
	)
	second = threading.Thread(
		target=lambda: results.setdefault("second", coordinator.send_message(text="second").text)
	)
	first.start()
	assert provider.first_started.wait(5)
	second.start()
	# The second request must remain outside the provider until turn one commits.
	assert len(provider.calls) == 1
	provider.release_first.set()
	first.join(5)
	second.join(5)
	assert not first.is_alive() and not second.is_alive()

	assert results == {"first": "reply-1", "second": "reply-2"}
	assert [_text(item) for item in provider.calls[1]] == ["first", "reply-1", "second"]
	loaded = repository.load("conversation").snapshot()
	assert [(item.role, _text(item)) for item in loaded] == [
		("user", "first"),
		("assistant", "reply-1"),
		("user", "second"),
		("assistant", "reply-2"),
	]


def test_provider_failure_after_partial_stream_does_not_persist_incomplete_turn(monkeypatch, tmp_path) -> None:
	"""A partial provider stream must not leave an incomplete persisted message."""
	monkeypatch.setattr(llm_module, "is_streaming_enabled", lambda: True)

	class PartialFailureProvider(ControlledProvider):
		def generate(self, messages, tools=None, stream_handler=None):
			if stream_handler is not None:
				stream_handler("partial", 7)
			raise RuntimeError("connection lost")

	repository = JsonConversationRepository(tmp_path / "conversations.json")
	coordinator = ChatCoordinator(
		ProviderLLMService(PartialFailureProvider()), repository=repository
	)
	coordinator.activate_conversation("conversation")
	partials: list[str] = []

	try:
		coordinator.send_message(
			text="retry me", progress_callback=lambda partial, _count: partials.append(partial)
		)
	except RuntimeError as error:
		assert str(error) == "connection lost"
	else:
		raise AssertionError("provider failure was not propagated")

	assert partials == ["partial"]
	assert coordinator.get_history() == []
	assert not repository.exists("conversation")


def test_queued_submission_from_old_conversation_cannot_enter_new_conversation(monkeypatch, tmp_path) -> None:
	"""A queued host event remains owned by the conversation that emitted it."""
	monkeypatch.setattr(llm_module, "is_streaming_enabled", lambda: False)
	provider = ControlledProvider()
	repository = JsonConversationRepository(tmp_path / "conversations.json")
	coordinator = ChatCoordinator(ProviderLLMService(provider), repository=repository)
	coordinator.activate_conversation("old")
	errors: list[Exception] = []

	first = threading.Thread(target=lambda: coordinator.send_message(text="in flight"))
	queued = threading.Thread(
		target=lambda: _capture_error(
			errors,
			lambda: coordinator.send_message(
				text="stale queued message", expected_conversation_id="old"
			),
		)
	)
	first.start()
	assert provider.first_started.wait(5)
	queued.start()
	coordinator.activate_conversation("new")
	provider.release_first.set()
	first.join(5)
	queued.join(5)
	assert not first.is_alive() and not queued.is_alive()

	assert len(provider.calls) == 1
	assert len(errors) == 1
	assert "conversation changed" in str(errors[0])
	assert coordinator.get_active_conversation_id() == "new"
	assert coordinator.get_history() == []
	assert not repository.exists("new")


def _capture_error(errors: list[Exception], operation) -> None:
	try:
		operation()
	except Exception as error:  # The assertion inspects the exact product failure below.
		errors.append(error)


def test_corrupted_conversation_store_recovers_and_can_be_rewritten(tmp_path) -> None:
	"""Corruption must not prevent startup or a subsequent durable save."""
	store_path = tmp_path / "conversations.json"
	store_path.write_text('{"messages":', encoding="utf-8")
	repository = JsonConversationRepository(store_path)

	assert repository.list_summaries() == []
	repository.save(
		"recovered",
		[Message(role="user", parts=(Part(type="text", text="مرحبا 👋"),))],
	)

	payload = json.loads(store_path.read_text(encoding="utf-8"))
	assert "recovered" in payload["messages"]
	assert _text(repository.load("recovered").snapshot()[0]) == "مرحبا 👋"


def test_unknown_tool_failure_is_returned_to_provider_and_turn_remains_consistent(
	monkeypatch, tmp_path
) -> None:
	"""An unsupported tool call must complete through the normal continuation loop."""
	monkeypatch.setattr(llm_module, "is_streaming_enabled", lambda: False)

	class ToolCallingProvider(ControlledProvider):
		def generate(self, messages, tools=None, stream_handler=None):
			self.calls.append(list(messages))
			if len(self.calls) == 1:
				return LLMResponse(
					text="",
					model="controlled-model",
					tool_calls=[ToolCall(name="missing_tool", arguments={}, id="call-1")],
				)
			return LLMResponse(text="Recovered after tool failure ✅", model="controlled-model")

	provider = ToolCallingProvider()
	repository = JsonConversationRepository(tmp_path / "conversations.json")
	service = ProviderLLMService(provider, tool_executor=ToolExecutor(ToolRegistry()))
	coordinator = ChatCoordinator(service, repository=repository)
	coordinator.activate_conversation("tools")

	response = coordinator.send_message(text="Use a tool")

	assert response.text == "Recovered after tool failure ✅"
	assert [message.role for message in provider.calls[1]] == ["user", "assistant", "tool"]
	tool_result = provider.calls[1][-1].parts[0]
	assert tool_result.tool_call_id == "call-1"
	assert "Unknown tool: missing_tool" in str(tool_result.text)
	persisted = repository.load("tools").snapshot()
	assert [message.role for message in persisted] == ["user", "assistant", "tool", "assistant"]
