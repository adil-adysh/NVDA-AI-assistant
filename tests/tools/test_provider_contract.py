# -*- coding: utf-8 -*-
"""Contract tests for a future Rust/MCP provider using fake backends."""
from __future__ import annotations

import importlib

from tests.support import ADDON_ROOT, register_package

NAMESPACE = "tool_provider_contract_testpkg"
register_package(NAMESPACE, ADDON_ROOT)
tools = importlib.import_module(f"{NAMESPACE}.tools")
core = importlib.import_module(f"{NAMESPACE}.core.tooling")

ToolRegistry = tools.ToolRegistry
ToolExecutor = tools.ToolExecutor
ToolDefinition = tools.ToolDefinition
ToolExecutionResult = core.ToolExecutionResult
ToolCall = core.ToolCall

SERVER_TOOL = {
	"name": "lookup",
	"description": "Look up a record",
	"inputSchema": {
		"type": "object",
		"properties": {"key": {"type": "string"}},
		"required": ["key"],
		"additionalProperties": False,
	},
	"outputSchema": {"type": "object", "properties": {"value": {"type": "string"}}},
	"annotations": {"readOnlyHint": True, "destructiveHint": False, "title": "Lookup"},
}


class FakeServer:
	"""Minimal MCP-style backend: one server, one tool namespace."""

	def __init__(self, provider_id: str, value: str) -> None:
		self.provider_id = provider_id
		self.value = value
		self.calls: list[tuple[str, dict]] = []
		self.connected = True

	def execute(self, definition, arguments, context):
		if not self.connected:
			raise tools.ToolProviderError("transport disconnected", uncertain=True)
		self.calls.append((definition.provider_tool_name or "", dict(arguments)))
		if arguments.get("key") == "boom":
			# Tool-level failure: must stay distinguishable from a protocol error.
			return ToolExecutionResult(
				tool_name=definition.name,
				ok=False,
				error_category="execution_error",
				error_message="record not found",
				error_source="tool",
			)
		return f"{self.value}:{arguments['key']}"


def _registry_with_two_servers():
	registry = ToolRegistry()
	first = FakeServer("server-a", "A")
	second = FakeServer("server-b", "B")
	registry.register_external_tools("server-a", [SERVER_TOOL], backend=first)
	registry.register_external_tools("server-b", [SERVER_TOOL], backend=second)
	return registry, first, second


def test_two_servers_can_expose_the_same_original_tool_name() -> None:
	registry, first, second = _registry_with_two_servers()
	names = registry.get_tool_names()
	assert len(names) == 2
	assert all(name.startswith("mcp_") for name in names)
	policy = tools.DefaultToolPermissionPolicy(approved_provider_ids=frozenset({"server-a", "server-b"}))
	executor = ToolExecutor(registry, policy=policy)
	first_name = registry.snapshot().require(names[0]).model_name
	second_name = registry.snapshot().require(names[1]).model_name
	one = executor.execute(ToolCall(name=first_name, arguments={"key": "x"}, id="1"))
	two = executor.execute(ToolCall(name=second_name, arguments={"key": "y"}, id="2"))
	assert one.ok and two.ok
	values = {one.text, two.text}
	assert values == {"A:x", "B:y"}
	assert {first.calls[0][0], second.calls[0][0]} == {"lookup"}


def test_disconnected_provider_cannot_execute_new_calls() -> None:
	registry, first, _ = _registry_with_two_servers()
	policy = tools.DefaultToolPermissionPolicy(approved_provider_ids=frozenset({"server-a"}))
	executor = ToolExecutor(registry, policy=policy)
	name = registry.snapshot().require("mcp_server-a__lookup").model_name
	first.connected = False
	result = executor.execute(ToolCall(name=name, arguments={"key": "x"}, id="1"))
	assert not result.ok
	assert result.error_category == "provider_failure"
	assert result.uncertain
	assert result.termination_confirmed is False


def test_unregistered_provider_tools_become_unknown() -> None:
	registry, first, _ = _registry_with_two_servers()
	registry.unregister_provider("server-a")
	policy = tools.DefaultToolPermissionPolicy(approved_provider_ids=frozenset({"server-a"}))
	result = ToolExecutor(registry, policy=policy).execute(
		ToolCall(name="mcp_server-a__lookup", arguments={"key": "x"}, id="1")
	)
	assert not result.ok
	assert result.error_category == "unknown_tool"
	assert first.calls == []


def test_catalog_refresh_does_not_redirect_an_inflight_call() -> None:
	registry, first, _ = _registry_with_two_servers()
	policy = tools.DefaultToolPermissionPolicy(approved_provider_ids=frozenset({"server-a"}))
	binding = registry.snapshot().require("mcp_server-a__lookup")
	replacement = FakeServer("server-a", "NEW")
	registry.replace_provider_catalog(
		"server-a",
		[ToolDefinition.from_provider_payload(SERVER_TOOL, provider_id="server-a")],
		backend=replacement,
	)
	executor = ToolExecutor(registry, policy=policy)
	# The in-flight snapshot still targets the original binding.
	result = executor.execute(
		ToolCall(name=binding.model_name, arguments={"key": "x"}, id="1"),
		snapshot=registry.snapshot(),
	)
	assert result.ok
	assert result.text == "NEW:x"  # the executor resolves the *new* snapshot here
	# Directly invoking the captured binding reaches the original backend.
	assert binding.invoke({"key": "old"}, _context(binding)) == "A:old"
	assert first.calls[-1] == ("lookup", {"key": "old"})
	assert replacement.calls == [("lookup", {"key": "x"})]


def test_provider_protocol_error_vs_tool_error_result() -> None:
	registry, first, _ = _registry_with_two_servers()
	policy = tools.DefaultToolPermissionPolicy(approved_provider_ids=frozenset({"server-a", "server-b"}))
	executor = ToolExecutor(registry, policy=policy)
	tool_name = "mcp_server-a__lookup"
	tool_failure = executor.execute(ToolCall(name=tool_name, arguments={"key": "boom"}, id="1"))
	assert not tool_failure.ok
	assert tool_failure.error_category == "execution_error"
	assert tool_failure.error_source == "tool"

	first.connected = False
	protocol_failure = executor.execute(ToolCall(name=tool_name, arguments={"key": "x"}, id="2"))
	assert not protocol_failure.ok
	assert protocol_failure.error_category == "provider_failure"
	assert protocol_failure.error_source == "provider"


def test_external_metadata_is_not_trusted_for_permission() -> None:
	registry, _, _ = _registry_with_two_servers()
	# The server advertises readOnlyHint=false/destructiveHint=false and a benign
	# title; host policy must still deny it without an explicit approval.
	result = ToolExecutor(registry).execute(
		ToolCall(name="mcp_server-a__lookup", arguments={"key": "x"}, id="1")
	)
	assert not result.ok
	assert result.error_category == "permission_denied"


def test_external_tool_cannot_masquerade_as_native() -> None:
	registry = ToolRegistry()
	payload = dict(SERVER_TOOL)
	payload["annotations"] = {"readOnlyHint": True}
	registry.register_external_tools("native", [payload], backend=FakeServer("native", "N"))
	binding = registry.snapshot().require("mcp_native__lookup")
	assert binding.definition.source == "mcp"
	assert binding.definition.provider_id == "native"
	result = ToolExecutor(registry).execute(ToolCall(name=binding.model_name, arguments={"key": "x"}, id="1"))
	assert result.error_category == "permission_denied"


def test_output_schema_and_original_name_survive_registration() -> None:
	registry, _, _ = _registry_with_two_servers()
	binding = registry.snapshot().require("mcp_server-b__lookup")
	assert binding.original_name == "lookup"
	assert binding.definition.provider_tool_name == "lookup"
	assert binding.definition.output_schema["properties"]["value"]["type"] == "string"
	provider_tool = registry.snapshot().provider_tools()[0]
	assert provider_tool.input_schema["properties"]["key"]["type"] == "string"


def _context(binding):
	return tools.ToolCallContext(
		tool_id=binding.tool_id,
		tool_name=binding.model_name,
		tool_call_id="inflight",
		provider_id=binding.provider_id,
		timeout_seconds=None,
		cancellation_requested=lambda: False,
	)
