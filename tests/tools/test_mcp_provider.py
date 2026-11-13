from __future__ import annotations

from tests.support.bootstrap import load_addon_module

provider_module = load_addon_module("tools.mcp_provider")
definitions = load_addon_module("tools.definition")
provider_types = load_addon_module("tools.provider")
executor_module = load_addon_module("tools.executor")
registry_module = load_addon_module("tools.registry")
policy_module = load_addon_module("tools.policy")
tooling = load_addon_module("core.tooling")


def test_mcp_provider_dispatches_exact_name_identity_and_preserves_result():
    observed = {}

    def dispatch(frame, timeout, cancelled):
        observed.update(frame=frame, timeout=timeout, cancelled=cancelled())
        return {
            "type": "mcp_manager_response", "success": True,
            "reply": {
                "ok": True, "is_error": False, "server_id": "server-a",
                "server_incarnation": 9, "catalog_generation": 12,
                "tool_name": "read:document", "tool_call_id": "call-17",
                "content": [{"type": "text", "text": "done"}],
                "structured_content": {"count": 2},
            },
        }

    provider = provider_module.McpToolProvider("mcp:server-a", dispatch)
    definition = definitions.ToolDefinition.from_provider_payload({
        "name": "read:document", "description": "Read a document",
        "inputSchema": {"type": "object", "properties": {}},
        "metadata": {"server_id": "server-a", "manager_session_id": "session-a", "server_incarnation": 9, "catalog_generation": 12},
    }, provider_id="mcp:server-a")
    context = provider_types.ToolCallContext(
        tool_id=definition.tool_id, tool_name="read:document", tool_call_id="call-17",
        provider_id="mcp:server-a", timeout_seconds=5,
        cancellation_requested=lambda: False,
    )

    result = provider.execute(definition, {}, context)
    assert observed["frame"]["server_incarnation"] == 9
    assert observed["frame"]["manager_session_id"] == "session-a"
    assert observed["frame"]["catalog_generation"] == 12
    assert observed["frame"]["tool_name"] == "read:document"
    assert observed["frame"]["tool_call_id"] == "call-17"
    assert result.ok is True
    assert result.content[0].text == "done"
    assert result.structured_content == {"count": 2}


def test_mcp_provider_reports_tool_error_without_hiding_content():
    provider = provider_module.McpToolProvider("mcp:server-a", lambda *_args: {
        "success": True,
        "reply": {"ok": True, "is_error": True,
            "content": [{"type": "text", "text": "tool rejected request"}]},
    })
    definition = definitions.ToolDefinition.from_provider_payload(
        {"name": "write", "inputSchema": {"type": "object"},
            "metadata": {"server_id": "server-a", "manager_session_id": "session-a", "server_incarnation": 9, "catalog_generation": 12}},
        provider_id="mcp:server-a")
    context = provider_types.ToolCallContext(
        tool_id=definition.tool_id, tool_name="write", tool_call_id=None,
        provider_id="mcp:server-a", timeout_seconds=2,
        cancellation_requested=lambda: False,
    )
    result = provider.execute(definition, {}, context)
    assert result.ok is False
    assert result.error_source == "tool"
    assert result.content[0].text == "tool rejected request"


def test_mcp_provider_maps_worker_failure_categories_to_actionable_safe_messages():
    provider = provider_module.McpToolProvider("mcp:server-a", lambda *_args: {
        "success": False,
        "error_code": "launch_failed",
        "error_message": "MCP manager process exited",
        "uncertain": False,
    })
    definition = definitions.ToolDefinition.from_provider_payload(
        {"name": "read", "inputSchema": {"type": "object"},
            "metadata": {"server_id": "server-a", "manager_session_id": "session-a", "server_incarnation": 9, "catalog_generation": 12}},
        provider_id="mcp:server-a")
    context = provider_types.ToolCallContext(
        tool_id=definition.tool_id, tool_name="read", tool_call_id=None,
        provider_id="mcp:server-a", timeout_seconds=2,
        cancellation_requested=lambda: False,
    )
    try:
        provider.execute(definition, {}, context)
    except Exception as error:
        assert "executable path" in error.safe_message
    else:
        raise AssertionError("worker launch failure must raise")


def test_mcp_tool_executes_only_through_existing_authorized_tool_executor():
    calls = []

    def dispatch(frame, timeout, cancelled):
        calls.append(frame)
        return {"success": True, "reply": {"ok": True, "is_error": False,
            "content": [{"type": "text", "text": "approved result"}]}}

    registry = registry_module.ToolRegistry()
    provider = provider_module.McpToolProvider("mcp:server-a", dispatch)
    definition = definitions.ToolDefinition.from_provider_payload({
        "name": "inspect", "inputSchema": {"type": "object"},
        "metadata": {"server_id": "server-a", "manager_session_id": "session-a", "server_incarnation": 1, "catalog_generation": 2},
    }, provider_id="mcp:server-a")
    registry.register_provider_tools("mcp:server-a", (definition,), backend=provider)
    tool_executor = executor_module.ToolExecutor(registry)
    name = registry.snapshot().definitions[0].name

    denied = tool_executor.execute(tooling.ToolCall(name=name, arguments={}, id="call-denied"))
    assert denied.error_category == "permission_denied"
    assert calls == []

    tool_executor.set_policy(policy_module.DefaultToolPermissionPolicy().with_approval(tool_id=definition.tool_id))
    result = tool_executor.execute(tooling.ToolCall(name=name, arguments={}, id="call-approved"))
    assert result.ok is True
    assert result.text == "approved result"
    assert result.tool_call_id == "call-approved"
    assert calls[0]["tool_name"] == "inspect"
