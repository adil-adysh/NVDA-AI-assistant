from __future__ import annotations

from tests.support.bootstrap import load_addon_module
from threading import Event

catalog_module = load_addon_module("tools.mcp_catalog")
registry_module = load_addon_module("tools.registry")
config_module = load_addon_module("config.mcp_servers")


def test_refresh_registers_server_identity_and_atomically_replaces_catalog():
    registry = registry_module.ToolRegistry()
    replies = {
        "mcp_connect_stdio": {"success": True, "reply": {"ok": True}},
        "mcp_poll_events": {"success": True, "reply": {"ok": True, "events": []}},
        "mcp_list_tools": {
            "success": True,
            "reply": {"ok": True, "server_id": "alpha", "manager_session_id": "session-alpha", "server_incarnation": 6,
                "catalog_generation": 3, "tools": [
                    {"name": "read", "description": "Read", "inputSchema": {"type": "object"}},
                    {"name": "write", "description": "Write", "inputSchema": {"type": "object"}},
                ]},
        },
    }
    calls = []
    service = catalog_module.McpCatalogService(registry, lambda frame, timeout, cancelled: calls.append(frame) or replies[frame["type"]])

    service.connect_stdio("alpha", "server.exe", ("--mode", "mcp"), {})
    snapshot = registry.snapshot()
    assert {binding.original_name for binding in snapshot.bindings.values()} == {"read", "write"}
    for binding in snapshot.bindings.values():
        assert binding.definition.metadata["server_id"] == "alpha"
        assert binding.definition.metadata["manager_session_id"] == "session-alpha"
        assert binding.definition.metadata["server_incarnation"] == 6
        assert binding.definition.metadata["catalog_generation"] == 3
    assert calls[0]["type"] == "mcp_connect_stdio"
    assert calls[1]["type"] == "mcp_list_tools"
    service.close()


def test_refresh_failure_leaves_previous_catalog_intact():
    registry = registry_module.ToolRegistry()
    call_number = 0

    def dispatch(frame, timeout, cancelled):
        nonlocal call_number
        call_number += 1
        if frame["type"] == "mcp_connect_stdio":
            return {"success": True, "reply": {"ok": True}}
        if frame["type"] == "mcp_poll_events":
            return {"success": True, "reply": {"ok": True, "events": []}}
        if call_number == 2:
            return {"success": True, "reply": {"ok": True, "server_id": "alpha", "manager_session_id": "session-alpha",
                "server_incarnation": 1, "catalog_generation": 1,
                "tools": [{"name": "old", "inputSchema": {"type": "object"}}]}}
        return {"success": False, "error_message": "manager unavailable"}

    service = catalog_module.McpCatalogService(registry, dispatch)
    service.connect_stdio("alpha", "server.exe")
    previous = registry.snapshot()
    try:
        service.refresh("alpha")
    except Exception:
        pass
    else:
        raise AssertionError("refresh should fail")
    assert registry.snapshot() is previous
    service.close()


def test_connected_state_is_independent_of_discovered_tool_count():
    registry = registry_module.ToolRegistry()
    replies = {
        "mcp_connect_stdio": {"success": True, "reply": {"ok": True}},
        "mcp_poll_events": {"success": True, "reply": {"ok": True, "events": []}},
        "mcp_list_tools": {"success": True, "reply": {
            "ok": True, "server_id": "empty", "manager_session_id": "session-empty",
            "server_incarnation": 1, "catalog_generation": 1, "tools": [],
        }},
    }
    service = catalog_module.McpCatalogService(
        registry,
        lambda frame, _timeout, _cancelled: replies[frame["type"]],
    )

    service.connect_stdio("empty", "server.exe")

    assert service.is_connected("empty") is True
    assert registry.get_enabled_definitions() == ()
    service.close()


def test_http_server_config_resolves_secret_without_persisting_it_in_config():
    registry = registry_module.ToolRegistry()
    calls = []
    replies = {
        "mcp_connect_http": {"success": True, "reply": {"ok": True}},
        "mcp_poll_events": {"success": True, "reply": {"ok": True, "events": []}},
        "mcp_list_tools": {"success": True, "reply": {
            "ok": True, "server_id": "remote", "manager_session_id": "session-remote",
            "server_incarnation": 1, "catalog_generation": 1, "tools": [],
        }},
    }
    service = catalog_module.McpCatalogService(
        registry,
        lambda frame, _timeout, _cancelled: calls.append(frame) or replies[frame["type"]],
        credential_resolver=lambda reference: "secret-value" if reference == "remote" else "",
    )
    server = config_module.McpServerConfig.from_dict({
        "server_id": "remote", "transport": "streamable_http",
        "url": "https://tools.example.test/mcp", "credential_ref": "remote",
    })

    service.connect_config(server)

    assert "secret-value" not in str(server.to_dict())
    assert calls[0]["auth_token"] == "secret-value"
    service.close()


def test_refresh_retries_stale_generation_response_with_a_bounded_attempt_count():
    registry = registry_module.ToolRegistry()
    calls = []

    def dispatch(frame, _timeout, _cancelled):
        calls.append(frame)
        if len(calls) == 1:
            return {"success": True, "reply": {"ok": False, "error": {"category": "stale_catalog"}}}
        return {"success": True, "reply": {
            "ok": True, "server_id": "alpha", "manager_session_id": "session-alpha",
            "server_incarnation": 1, "catalog_generation": 2,
            "tools": [{"name": "fresh", "inputSchema": {"type": "object"}}],
        }}

    service = catalog_module.McpCatalogService(registry, dispatch)
    definitions = service.refresh("alpha")

    assert [frame["type"] for frame in calls] == ["mcp_list_tools", "mcp_list_tools"]
    assert definitions[0].provider_tool_name == "fresh"
    service.close()


def test_resync_retires_catalogs_missing_from_manager_status():
    registry = registry_module.ToolRegistry()
    status = {"success": True, "reply": {"ok": True, "servers": []}}
    service = catalog_module.McpCatalogService(registry, lambda _frame, _timeout, _cancelled: status)
    registry.register_external_tools(
        "mcp:gone", [{"name": "read", "inputSchema": {"type": "object"}}], backend=object()
    )
    service._connected_servers.add("gone")

    service._resynchronize()

    assert not service.is_connected("gone")
    assert registry.get_definitions() == []
    service.close()


def test_repeated_stale_catalog_replies_stop_after_three_attempts():
    calls = []

    def dispatch(frame, _timeout, _cancelled):
        calls.append(frame)
        return {"success": True, "reply": {"ok": False, "error": {"category": "stale_catalog"}}}

    service = catalog_module.McpCatalogService(registry_module.ToolRegistry(), dispatch)
    try:
        service.refresh("alpha")
    except Exception as error:
        assert "bounded refresh attempt" in str(error)
    else:
        raise AssertionError("repeated stale catalogs must fail closed")
    assert len(calls) == 3
    service.close()


def test_notification_loss_resynchronizes_all_servers_and_list_change_targets_one():
    service = catalog_module.McpCatalogService(registry_module.ToolRegistry(), lambda *_args: {})
    resyncs = []
    refreshes = []
    service._resynchronize = lambda: resyncs.append(True)
    service._schedule_refresh = lambda server_id: refreshes.append(server_id)

    service._handle_manager_event({"event": "notification_stream_closed", "server_id": "alpha"})
    service._handle_manager_event({"event": "tool_list_changed", "server_id": "beta"})

    assert resyncs == [True]
    assert refreshes == ["beta"]
    service.close()


def test_notification_during_refresh_coalesces_a_follow_up_catalog_read():
	registry = registry_module.ToolRegistry()
	first_started = Event()
	release_first = Event()
	second_published = Event()
	calls = 0
	original_replace = registry.replace_provider_catalog

	def replace(provider_id, definitions, *, backend):
		result = original_replace(provider_id, definitions, backend=backend)
		if definitions and definitions[0].metadata["catalog_generation"] == 2:
			second_published.set()
		return result

	registry.replace_provider_catalog = replace

	def dispatch(frame, _timeout, _cancelled):
		nonlocal calls
		if frame["type"] != "mcp_list_tools":
			return {"success": True, "reply": {"ok": True, "events": []}}
		calls += 1
		if calls == 1:
			first_started.set()
			assert release_first.wait(2)
			name, generation = "old", 1
		else:
			name, generation = "fresh", 2
		return {"success": True, "reply": {
			"ok": True, "server_id": "alpha", "manager_session_id": "session",
			"server_incarnation": 3, "catalog_generation": generation,
			"tools": [{"name": name, "inputSchema": {"type": "object"}}],
		}}

	service = catalog_module.McpCatalogService(registry, dispatch)
	service._connected_servers.add("alpha")
	service._schedule_refresh("alpha")
	assert first_started.wait(1)
	service._handle_manager_event({"event": "tool_list_changed", "server_id": "alpha"})
	release_first.set()
	assert second_published.wait(2), "notification during refresh did not schedule a follow-up"
	assert calls == 2
	assert registry.get_enabled_definitions()[0].provider_tool_name == "fresh"
	service.close()


def test_disconnect_fences_inflight_notification_refresh():
	registry = registry_module.ToolRegistry()
	started = Event()
	release = Event()

	def dispatch(frame, _timeout, _cancelled):
		if frame["type"] == "mcp_list_tools":
			started.set()
			assert release.wait(2)
			return {"success": True, "reply": {
				"ok": True, "server_id": "alpha", "manager_session_id": "session",
				"server_incarnation": 3, "catalog_generation": 1,
				"tools": [{"name": "stale", "inputSchema": {"type": "object"}}],
			}}
		return {"success": True, "reply": {"ok": True}}

	service = catalog_module.McpCatalogService(registry, dispatch)
	service._connected_servers.add("alpha")
	service._schedule_refresh("alpha")
	assert started.wait(1)
	service.disconnect("alpha")
	release.set()
	service._refresh_pool.shutdown(wait=True)
	assert registry.get_enabled_definitions() == ()
	assert not service.is_connected("alpha")
	assert "alpha" in service._blocked_servers
	service.close()


def test_mcp_catalog_accepts_compatible_draft7_schema_without_losing_constraints():
    definition = catalog_module.McpCatalogService._tool_definition(
        {
            "name": "read",
            "inputSchema": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
                "properties": {"count": {"type": "integer", "minimum": 1}},
                "required": ["count"],
                "additionalProperties": False,
            },
        },
        provider_id="mcp:bridge",
        server_id="bridge",
        server_incarnation=1,
        manager_session_id="session",
        catalog_generation=1,
    )

    assert definition.input_schema["required"] == ("count",)
    assert definition.input_schema["properties"]["count"]["minimum"] == 1
    assert "$schema" not in definition.input_schema


def test_mcp_catalog_rejects_untranslated_draft7_validation_keywords():
    try:
        catalog_module.McpCatalogService._tool_definition(
            {
                "name": "read",
                "inputSchema": {
                    "$schema": "http://json-schema.org/draft-07/schema#",
                    "type": "object",
                    "dependencies": {"mode": ["value"]},
                },
            },
            provider_id="mcp:bridge",
            server_id="bridge",
            server_incarnation=1,
            manager_session_id="session",
            catalog_generation=1,
        )
    except Exception as error:
        assert "Draft 7 keyword 'dependencies'" in str(error)
    else:
        raise AssertionError("untranslated Draft 7 assertions must fail closed")


def test_mcp_catalog_rejects_nested_schema_dialect_without_root_declaration():
    try:
        catalog_module.McpCatalogService._tool_definition(
            {
                "name": "read",
                "inputSchema": {
                    "type": "object",
                    "properties": {"value": {"$schema": "https://json-schema.org/draft/2020-12/schema"}},
                },
            },
            provider_id="mcp:bridge",
            server_id="bridge",
            server_incarnation=1,
            manager_session_id="session",
            catalog_generation=1,
        )
    except Exception as error:
        assert "nested schema dialect" in str(error)
    else:
        raise AssertionError("nested dialects must not be silently ignored")


def test_closed_catalog_service_fences_new_worker_commands():
    calls = []
    service = catalog_module.McpCatalogService(
        registry_module.ToolRegistry(),
        lambda frame, _timeout, _cancelled: calls.append(frame) or {"success": True, "reply": {"ok": True}},
    )
    service.close()

    try:
        service.connect_stdio("late", "server.exe")
    except Exception as error:
        assert "closed" in str(error)
    else:
        raise AssertionError("closed catalog service must reject new operations")
    assert calls == []


def test_manager_failure_categories_produce_actionable_safe_messages():
    launch = {
        "success": True,
        "reply": {"ok": False, "error": {"category": "launch_failed", "message": "server process could not be started"}},
    }
    try:
        catalog_module.McpCatalogService._require_manager_success(launch)
    except Exception as error:
        assert "executable path" in error.safe_message
    else:
        raise AssertionError("launch failure must raise")

    handshake = {
        "success": True,
        "reply": {"ok": False, "error": {"category": "protocol_error", "message": "MCP initialization failed"}},
    }
    try:
        catalog_module.McpCatalogService._require_manager_success(handshake)
    except Exception as error:
        assert "handshake" in error.safe_message
        assert "environment variables" in error.safe_message
    else:
        raise AssertionError("protocol failure must raise")

    unknown = {
        "success": True,
        "reply": {"ok": False, "error": {"category": "surprise", "message": "x"}},
    }
    try:
        catalog_module.McpCatalogService._require_manager_success(unknown)
    except Exception as error:
        assert "could not be updated" in error.safe_message
    else:
        raise AssertionError("unknown failure must raise")


def test_worker_manager_failure_categories_produce_actionable_safe_messages():
    # The worker reports manager startup/transport failures as ``success:
    # false`` with ``error_code`` rather than a manager reply.  Those failures
    # must not collapse to the generic "connection failed" message.
    launch = {
        "success": False,
        "error_code": "launch_failed",
        "error_message": "MCP manager process exited",
    }
    try:
        catalog_module.McpCatalogService._require_manager_success(launch)
    except Exception as error:
        assert "executable path" in error.safe_message
    else:
        raise AssertionError("worker launch failure must raise")

    capacity = {
        "success": False,
        "error_code": "capacity",
        "error_message": "MCP manager request capacity reached",
    }
    try:
        catalog_module.McpCatalogService._require_manager_success(capacity)
    except Exception as error:
        assert "Too many MCP operations" in error.safe_message
    else:
        raise AssertionError("worker capacity failure must raise")
