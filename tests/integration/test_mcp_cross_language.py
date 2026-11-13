from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.support.bootstrap import load_addon_module

MANAGER = os.environ.get("NVDA_AI_MCP_MANAGER")
FIXTURE = os.environ.get("NVDA_AI_MCP_FIXTURE_SERVER")
if not MANAGER or not FIXTURE:
    pytest.skip("set NVDA_AI_MCP_MANAGER and NVDA_AI_MCP_FIXTURE_SERVER to run cross-language MCP acceptance", allow_module_level=True)

mcp_manager = load_addon_module("worker.mcp_manager")
runtime_commands = load_addon_module("worker.runtime_commands")
catalog_module = load_addon_module("tools.mcp_catalog")
registry_module = load_addon_module("tools.registry")
executor_module = load_addon_module("tools.executor")
policy_module = load_addon_module("tools.policy")
tooling = load_addon_module("core.tooling")
messages_module = load_addon_module("core.messages")
load_addon_module("tools")
llm_module = load_addon_module("service.llm")
coordinator_module = load_addon_module("service.chat.coordinator")
repository_module = load_addon_module("service.chat.repository_backends")


class _Worker:
    def __init__(self, client):
        self._mcp_manager_client = client

    def get_mcp_manager(self):
        return self._mcp_manager_client


def test_python_executor_calls_fixture_through_rust_rmcp_manager():
    manager_path = Path(MANAGER)
    fixture_path = Path(FIXTURE)
    assert manager_path.is_file()
    assert fixture_path.is_file()
    client = mcp_manager.McpManagerClient((str(manager_path),))
    client.start()
    worker = _Worker(client)

    def dispatch(frame, timeout, cancelled):
        output = []
        runtime_commands.execute_runtime_command(
            worker, frame, output.append, cancellation_requested=cancelled,
        )
        assert output, "worker command did not produce a terminal response"
        return output[-1]

    registry = registry_module.ToolRegistry()
    catalog = catalog_module.McpCatalogService(registry, dispatch)
    try:
        definitions = catalog.connect_stdio("fixture", str(fixture_path), timeout=15)
        definition = next(item for item in definitions if item.provider_tool_name == "echo")
        snapshot = registry.snapshot()
        executor = executor_module.ToolExecutor(registry)
        malformed = executor.execute(
            tooling.ToolCall(name=definition.name, arguments={}, id="mcp-invalid"),
            snapshot=snapshot,
        )
        assert malformed.error_category == "invalid_arguments"
        denied = executor.execute(
            tooling.ToolCall(name=definition.name, arguments={"value": "safe"}, id="mcp-denied"),
            snapshot=snapshot,
        )
        assert denied.error_category == "permission_denied"
        executor.set_policy(policy_module.DefaultToolPermissionPolicy().with_approval(tool_id=definition.tool_id))
        result = executor.execute(
            tooling.ToolCall(name=definition.name, arguments={"value": {"answer": 42}}, id="mcp-call-42"),
            snapshot=snapshot,
        )
        assert result.ok is True
        assert result.tool_call_id == "mcp-call-42"
        assert result.structured_content["value"]["answer"] == 42
        assert result.metadata["server_id"] == "fixture"
        assert result.metadata["manager_session_id"]
    finally:
        catalog.close()
        client.close()


def test_chat_tool_loop_executes_mcp_and_persists_correlated_result(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_module, "is_streaming_enabled", lambda: False)
    client = mcp_manager.McpManagerClient((str(Path(MANAGER)),))
    client.start()
    worker = _Worker(client)

    def dispatch(frame, timeout, cancelled):
        output = []
        runtime_commands.execute_runtime_command(
            worker, frame, output.append, cancellation_requested=cancelled,
        )
        return output[-1]

    registry = registry_module.ToolRegistry()
    catalog = catalog_module.McpCatalogService(registry, dispatch)

    class ScriptedChatProvider:
        model = "fixture-chat"

        def __init__(self):
            self.calls = 0

        def provider_name(self):
            return "deterministic MCP chat"

        def supports_streaming(self):
            return False

        def supports_image_description(self):
            return False

        def list_models(self):
            return ()

        def get_model_info(self, model_name=None):
            return None

        def ensure_model_available(self, on_progress=None):
            return self.model

        def generate(self, messages, tools=None, stream_handler=None):
            self.calls += 1
            if self.calls == 1:
                target = next(tool for tool in tools if tool.name.endswith("__echo"))
                return messages_module.LLMResponse(
                    text="", tool_calls=[tooling.ToolCall(
                        name=target.name,
                        arguments={"value": {"answer": 42}},
                        id="chat-mcp-call",
                    )], model=self.model,
                )
            result_part = next(part for part in messages[-1].parts if part.type == "tool_result")
            return messages_module.LLMResponse(
                text=f"fixture={result_part.text}", model=self.model,
            )

        def close(self):
            return None

    try:
        definitions = catalog.connect_stdio("fixture-chat", str(Path(FIXTURE)), timeout=15)
        echo = next(item for item in definitions if item.provider_tool_name == "echo")
        executor = executor_module.ToolExecutor(registry)
        executor.set_policy(policy_module.DefaultToolPermissionPolicy().with_approval(tool_id=echo.tool_id))
        chat = llm_module.ProviderLLMService(ScriptedChatProvider(), tool_executor=executor)
        repository = repository_module.JsonConversationRepository(tmp_path / "conversations.json")
        coordinator = coordinator_module.ChatCoordinator(chat, repository=repository)
        coordinator.activate_conversation("mcp-chat")

        response = coordinator.send_message(
            text="Use the approved echo tool.", tool_catalog=registry.snapshot(),
        )

        assert response.text.startswith("fixture=")
        saved = repository.load("mcp-chat").snapshot()
        tool_messages = [message for message in saved if message.role == "tool"]
        assert len(tool_messages) == 1
        part = tool_messages[0].parts[0]
        assert part.tool_call_id == "chat-mcp-call"
        assert part.tool_result["tool_id"] == echo.tool_id
        assert part.tool_result["structured_content"]["value"]["answer"] == 42
    finally:
        catalog.close()
        client.close()
