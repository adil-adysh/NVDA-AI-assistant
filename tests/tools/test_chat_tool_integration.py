# -*- coding: utf-8 -*-
"""Deterministic full-path chat/tool integration tests."""
from __future__ import annotations

import importlib
import json
import threading
from datetime import datetime

from tests.support import ADDON_ROOT, register_package

NAMESPACE = "tool_chat_integration_testpkg"
register_package(NAMESPACE, ADDON_ROOT)
tools = importlib.import_module(f"{NAMESPACE}.tools")
core = importlib.import_module(f"{NAMESPACE}.core.tooling")
messages_module = importlib.import_module(f"{NAMESPACE}.core.messages")
llm_module = importlib.import_module(f"{NAMESPACE}.service.llm")
coordinator_module = importlib.import_module(f"{NAMESPACE}.service.chat.coordinator")
repository_module = importlib.import_module(f"{NAMESPACE}.service.chat.repository_backends")

ToolCall = core.ToolCall
LLMResponse = messages_module.LLMResponse
JsonConversationRepository = repository_module.JsonConversationRepository


class ScriptedProvider:
	"""Provider fake driven by explicit per-call scripts (no spontaneous tools)."""

	def __init__(self, scripts: list[callable], model: str = "deterministic-model") -> None:
		self._scripts = scripts
		self.model = model
		self.calls: list[tuple[list, object]] = []
		self._lock = threading.Lock()

	def provider_name(self) -> str:
		return "deterministic"

	def supports_streaming(self) -> bool:
		return True

	def supports_image_description(self) -> bool:
		return False

	def list_models(self):
		return ()

	def get_model_info(self, model_name=None):
		return None

	def ensure_model_available(self, on_progress=None):
		return self.model

	def generate(self, messages, tools=None, stream_handler=None):
		with self._lock:
			index = len(self.calls)
			self.calls.append((list(messages), tools))
		script = self._scripts[min(index, len(self._scripts) - 1)]
		response = script(messages, tools)
		if stream_handler is not None and response.text:
			stream_handler(response.text, len(response.text))
		return response

	def close(self):
		return None


def _time_call(call_id: str = "call-1") -> ToolCall:
	return ToolCall(name="get_time", arguments={}, id=call_id)


def _tool_texts(message) -> list[str]:
	return [part.text or "" for part in message.parts if part.type == "tool_result"]


def _build_stack(*, read_only_policy=True):
	registry = tools.ToolRegistry()
	tools.register_default_tools(registry)
	executor = tools.ToolExecutor(registry)
	return registry, executor


def _answer_with_time(messages, tools_arg=None) -> LLMResponse:
	last_tool = next(part for part in messages[-1].parts if part.type == "tool_result")
	return LLMResponse(text=f"time={last_tool.text}", model="deterministic-model")


def test_get_time_through_normal_chat_path(monkeypatch, tmp_path) -> None:
	monkeypatch.setattr(llm_module, "is_streaming_enabled", lambda: False)
	registry, executor = _build_stack()
	provider = ScriptedProvider(
		[
			lambda _messages, _tools: LLMResponse(text="", tool_calls=[_time_call()]),
			_answer_with_time,
		]
	)
	service = llm_module.ProviderLLMService(provider, tool_executor=executor)
	repository = JsonConversationRepository(tmp_path / "conversations.json")
	coordinator = coordinator_module.ChatCoordinator(service, repository=repository)
	coordinator.activate_conversation("time-chat")

	response = coordinator.send_message(text="What time is it?", tool_catalog=registry.snapshot())

	assert response.text.startswith("time=")
	parsed = datetime.fromisoformat(response.text.removeprefix("time="))
	assert parsed.year >= 2024
	# The catalog reached the provider and the model was told about the tool.
	assert [tool.name for tool in provider.calls[0][1]] == ["get_time"]
	# Result correlation: assistant tool_call -> matching tool result.
	second_request = provider.calls[1][0]
	assert [message.role for message in second_request] == ["user", "assistant", "tool"]
	tool_part = second_request[-1].parts[0]
	assert tool_part.tool_call_id == "call-1"
	assert tool_part.tool_result["ok"] is True
	assert coordinator.last_turn_committed()

	saved = repository.load("time-chat").snapshot()
	assert [message.role for message in saved] == ["user", "assistant", "tool", "assistant"]
	assert [part.tool_call_id for part in saved[2].parts] == ["call-1"]
	assert saved[2].parts[0].tool_result["tool_id"] == "native:get_time"


def test_multiple_tool_calls_keep_correlation(monkeypatch, tmp_path) -> None:
	monkeypatch.setattr(llm_module, "is_streaming_enabled", lambda: False)
	registry, executor = _build_stack()
	provider = ScriptedProvider(
		[
			lambda _messages, _tools: LLMResponse(
				text="",
				tool_calls=[_time_call("a"), _time_call("b")],
			),
			lambda messages, _tools: LLMResponse(
				text="both=" + ",".join(text for message in messages[-2:] for text in _tool_texts(message)),
				model="deterministic-model",
			),
		]
	)
	service = llm_module.ProviderLLMService(provider, tool_executor=executor)
	coordinator = coordinator_module.ChatCoordinator(service)
	coordinator.activate_conversation("multi")

	response = coordinator.send_message(text="two times", tool_catalog=registry.snapshot())

	assert response.text.startswith("both=")
	second_request = provider.calls[1][0]
	tool_messages = [message for message in second_request if message.role == "tool"]
	assert [part.tool_call_id for message in tool_messages for part in message.parts] == ["a", "b"]


def test_streaming_generation_with_tool_call(monkeypatch) -> None:
	monkeypatch.setattr(llm_module, "is_streaming_enabled", lambda: True)
	registry, executor = _build_stack()
	provider = ScriptedProvider(
		[
			lambda _messages, _tools: LLMResponse(text="", tool_calls=[_time_call()]),
			_answer_with_time,
		]
	)
	service = llm_module.ProviderLLMService(provider, tool_executor=executor)
	coordinator = coordinator_module.ChatCoordinator(service)
	coordinator.activate_conversation("stream")
	partials: list[str] = []

	response = coordinator.send_message(
		text="time?",
		tool_catalog=registry.snapshot(),
		progress_callback=lambda text, _count: partials.append(text),
	)

	assert "time=" in partials[-1]
	assert response.text.startswith("time=")


def test_provider_without_tool_support_still_completes(monkeypatch) -> None:
	monkeypatch.setattr(llm_module, "is_streaming_enabled", lambda: True)
	registry, executor = _build_stack()
	provider = ScriptedProvider([lambda _messages, _tools: LLMResponse(text="plain answer")])
	service = llm_module.ProviderLLMService(provider, tool_executor=executor)
	coordinator = coordinator_module.ChatCoordinator(service)
	coordinator.activate_conversation("no-tools")

	response = coordinator.send_message(text="hello", tool_catalog=registry.snapshot())

	assert response.text == "plain answer"
	assert [message.role for message in coordinator.get_history()] == ["user", "assistant"]


def test_tool_execution_limit_is_bounded_and_history_stays_valid(monkeypatch) -> None:
	monkeypatch.setattr(llm_module, "is_streaming_enabled", lambda: False)
	registry, executor = _build_stack()
	executed: list[str] = []

	def handler(arguments):
		executed.append("call")
		return "tick"

	registry.update(
		"native:get_time",
		definition=tools.ToolDefinition(
			name="get_time",
			description="tick",
			input_schema={"type": "object", "properties": {}},
			annotations=tools.ToolAnnotations(read_only_hint=True),
			executor=handler,
		),
	)

	call_index = {"value": 0}

	def always_calls(_messages, _tools):
		call_index["value"] += 1
		return LLMResponse(text="", tool_calls=[_time_call(f"call-{call_index['value']}")])

	provider = ScriptedProvider([always_calls])
	service = llm_module.ProviderLLMService(provider, tool_executor=executor)
	coordinator = coordinator_module.ChatCoordinator(service)
	coordinator.activate_conversation("bounded")

	response = coordinator.send_message(text="loop", tool_catalog=registry.snapshot())

	assert len(executed) == llm_module.ProviderLLMService.MAX_TOOL_STEPS
	assert len(provider.calls) == llm_module.ProviderLLMService.MAX_TOOL_STEPS + 1
	assert response.tool_calls is None
	assert response.raw["tool_loop_limit_reached"] is True
	assert response.text

	history = coordinator.get_history()
	roles = [message.role for message in history]
	assert roles[0] == "user"
	assert roles[-1] == "assistant"
	assert roles.count("assistant") == llm_module.ProviderLLMService.MAX_TOOL_STEPS + 2
	assert roles.count("tool") == llm_module.ProviderLLMService.MAX_TOOL_STEPS + 1
	# Every assistant tool_call is immediately followed by matching tool results.
	for index, message in enumerate(history):
		if message.tool_calls:
			assert history[index + 1].role == "tool"
	assert history[-1].role == "assistant"


def test_tool_turn_is_discarded_when_conversation_changes(monkeypatch) -> None:
	monkeypatch.setattr(llm_module, "is_streaming_enabled", lambda: False)
	registry, executor = _build_stack()
	coordinator_ref: dict[str, object] = {}

	def switching_handler(arguments):
		coordinator = coordinator_ref["coordinator"]
		coordinator.activate_conversation("other")
		return "tick"

	registry.update(
		"native:get_time",
		definition=tools.ToolDefinition(
			name="get_time",
			description="tick",
			input_schema={"type": "object", "properties": {}},
			annotations=tools.ToolAnnotations(read_only_hint=True),
			executor=switching_handler,
		),
	)
	provider = ScriptedProvider(
		[
			lambda _messages, _tools: LLMResponse(text="", tool_calls=[_time_call()]),
			lambda _messages, _tools: LLMResponse(text="stale answer"),
		]
	)
	service = llm_module.ProviderLLMService(provider, tool_executor=executor)
	coordinator = coordinator_module.ChatCoordinator(service)
	coordinator.activate_conversation("start")
	coordinator_ref["coordinator"] = coordinator

	coordinator.send_message(text="time", tool_catalog=registry.snapshot())

	assert coordinator.get_active_conversation_id() == "other"
	assert coordinator.get_history() == []
	assert coordinator.last_turn_committed() is False


def test_tool_result_envelope_survives_repository_round_trip(tmp_path) -> None:
	repository = JsonConversationRepository(tmp_path / "conversations.json")
	part = importlib.import_module(f"{NAMESPACE}.core.canonical").Part
	message_cls = importlib.import_module(f"{NAMESPACE}.core.canonical").Message
	result = core.ToolExecutionResult(
		tool_name="get_time",
		tool_call_id="call-9",
		tool_id="native:get_time",
		ok=False,
		error_category="timeout",
		error_message="timed out",
		timed_out=True,
		uncertain=True,
		termination_confirmed=False,
	)
	repository.save(
		"round-trip",
		[
			message_cls(
				role="tool",
				parts=(
					part(
						type="tool_result",
						text="timed out",
						tool_name="get_time",
						tool_call_id="call-9",
						tool_result=result.to_dict(),
					),
				),
			)
		],
	)
	loaded = repository.load("round-trip").snapshot()[0].parts[0]
	assert loaded.tool_call_id == "call-9"
	restored = core.ToolExecutionResult.from_dict(loaded.tool_result)
	assert restored is not None
	assert restored.error_category == "timeout"
	assert restored.timed_out and restored.uncertain
	assert restored.termination_confirmed is False
	# The persisted envelope is JSON round-trippable.
	assert json.loads(json.dumps(loaded.tool_result))["ok"] is False
