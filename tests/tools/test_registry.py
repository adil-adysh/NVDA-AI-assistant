# -*- coding: utf-8 -*-
"""Dynamic registry lifecycle, naming, generations and concurrency."""
from __future__ import annotations

import importlib
import threading

import pytest

from tests.support import ADDON_ROOT, register_package

NAMESPACE = "tool_registry_testpkg"
register_package(NAMESPACE, ADDON_ROOT)
tools_module = importlib.import_module(f"{NAMESPACE}.tools")
ToolDefinition = tools_module.ToolDefinition
ToolRegistry = tools_module.ToolRegistry
ToolCall = importlib.import_module(f"{NAMESPACE}.core.tooling").ToolCall
ToolNameConflictError = tools_module.ToolNameConflictError
ToolAlreadyRegisteredError = tools_module.ToolAlreadyRegisteredError


def _native(name: str = "echo", result: str = "ok") -> ToolDefinition:
	return ToolDefinition(
		name=name,
		description=f"{name} tool",
		input_schema={"type": "object", "properties": {}},
		executor=lambda arguments: result,
	)


def _external(name: str = "lookup") -> dict:
	return {
		"name": name,
		"description": f"{name} from server",
		"inputSchema": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
		"outputSchema": {"type": "object", "properties": {"value": {"type": "string"}}},
	}


class FakeBackend:
	def __init__(self, provider_id: str, result: str = "ok") -> None:
		self.provider_id = provider_id
		self.result = result
		self.calls: list[tuple[str, dict]] = []

	def execute(self, definition, arguments, context):
		self.calls.append((definition.provider_tool_name or definition.name, dict(arguments)))
		return self.result


def test_register_and_enabled_definitions() -> None:
	registry = ToolRegistry()
	registry.register_tool(_native())
	assert registry.generation == 1
	assert registry.get_tool_names() == ["echo"]
	snapshot = registry.snapshot()
	assert snapshot.generation == 1
	assert snapshot.require("echo").definition.tool_id == "native:echo"
	assert snapshot.definition_for("echo").input_schema == {"type": "object", "properties": {}}


def test_duplicate_registration_is_rejected() -> None:
	registry = ToolRegistry()
	registry.register_tool(_native())
	with pytest.raises(ToolAlreadyRegisteredError):
		registry.register_tool(_native())
	assert len(registry.get_enabled_definitions()) == 1


def test_unregister_removes_tool_from_new_snapshots() -> None:
	registry = ToolRegistry()
	registry.register_tool(_native())
	old_snapshot = registry.snapshot()
	assert registry.unregister("echo") is True
	assert registry.get_tool_names() == []
	assert old_snapshot.resolve("echo") is not None
	assert registry.snapshot().resolve("echo") is None
	assert registry.unregister("echo") is False


def test_update_replaces_handler_and_metadata() -> None:
	registry = ToolRegistry()
	registry.register_tool(_native(result="first"))
	updated = registry.update(
		"native:echo",
		definition=ToolDefinition(
			name="echo",
			description="updated",
			input_schema={"type": "object", "properties": {}},
			executor=lambda arguments: "second",
		),
	)
	assert updated.description == "updated"
	binding = registry.snapshot().require("echo")
	assert binding.tool_id == "native:echo"


def test_native_name_conflict_is_detected() -> None:
	registry = ToolRegistry()
	registry.register_tool(_native("echo"))
	conflicting = ToolDefinition(
		name="echo",
		description="other identity",
		input_schema={"type": "object", "properties": {}},
		tool_id="native:other",
		executor=lambda arguments: "x",
	)
	with pytest.raises(ToolNameConflictError):
		registry.register_tool(conflicting)


def test_external_tools_are_namespaced_and_reversible() -> None:
	registry = ToolRegistry()
	backend = FakeBackend("server-a")
	registry.register_external_tools("server-a", [_external()], backend=backend)
	binding = registry.snapshot().require("mcp_server-a__lookup")
	assert binding.original_name == "lookup"
	assert binding.definition.provider_tool_name == "lookup"
	assert binding.provider_id == "server-a"
	assert binding.definition.output_schema["properties"]["value"]["type"] == "string"


def test_two_servers_may_expose_the_same_original_tool_name() -> None:
	registry = ToolRegistry()
	first = FakeBackend("server-a", "a")
	second = FakeBackend("server-b", "b")
	registry.register_external_tools("server-a", [_external()], backend=first)
	registry.register_external_tools("server-b", [_external()], backend=second)
	names = registry.get_tool_names()
	assert len(set(names)) == 2
	assert registry.snapshot().require(names[0]).original_name == "lookup"
	assert registry.snapshot().require(names[1]).original_name == "lookup"
	assert names[0].startswith("mcp_server-a__") or names[0].startswith("mcp_server-b__")


def test_provider_catalog_replacement_is_atomic_and_single_generation() -> None:
	registry = ToolRegistry()
	registry.register_external_tools("server-a", [_external("one")], backend=FakeBackend("server-a"))
	generation_before = registry.generation
	created = registry.replace_provider_catalog(
		"server-a",
		[
			ToolDefinition.from_provider_payload(_external("two"), provider_id="server-a"),
			ToolDefinition.from_provider_payload(_external("three"), provider_id="server-a"),
		],
		backend=FakeBackend("server-a"),
	)
	assert {definition.provider_tool_name for definition in created} == {"two", "three"}
	assert registry.generation == generation_before + 1
	assert registry.snapshot().resolve("mcp_server-a__one") is None
	assert registry.snapshot().resolve("mcp_server-a__two") is not None


def test_failed_catalog_replacement_leaves_previous_catalog_intact() -> None:
	registry = ToolRegistry()
	registry.register_external_tools("server-a", [_external("one")], backend=FakeBackend("server-a"))
	before = registry.snapshot()
	with pytest.raises(tools_module.ToolSchemaError):
		registry.replace_provider_catalog(
			"server-a",
			[ToolDefinition.from_provider_payload(
				{"name": "broken", "inputSchema": {"type": "object", "properties": []}},
				provider_id="server-a",
			)],
			backend=FakeBackend("server-a"),
		)
	after = registry.snapshot()
	assert after is before
	assert after.resolve("mcp_server-a__one") is not None


def test_unregister_provider_removes_only_that_provider() -> None:
	registry = ToolRegistry()
	registry.register_external_tools("server-a", [_external("one")], backend=FakeBackend("server-a"))
	registry.register_external_tools("server-b", [_external("two")], backend=FakeBackend("server-b"))
	registry.register_tool(_native())
	assert registry.unregister_provider("server-a") == 1
	assert registry.snapshot().resolve("mcp_server-a__one") is None
	assert registry.snapshot().resolve("mcp_server-b__two") is not None
	assert registry.snapshot().resolve("echo") is not None


def test_availability_hides_tools_without_losing_identity() -> None:
	registry = ToolRegistry()
	backend = FakeBackend("server-a")
	registry.register_external_tools("server-a", [_external()], backend=backend)
	registry.set_provider_available("server-a", False)
	assert registry.get_tool_names() == []
	registry.set_provider_available("server-a", True)
	binding = registry.snapshot().require("mcp_server-a__lookup")
	assert binding.tool_id == "mcp:server-a:lookup"

	registry.register_tool(_native())
	registry.set_tool_available("echo", False)
	assert "echo" not in registry.get_tool_names()
	registry.set_tool_available("native:echo", True)
	assert "echo" in registry.get_tool_names()


def test_snapshot_is_immutable() -> None:
	registry = ToolRegistry()
	registry.register_tool(_native())
	snapshot = registry.snapshot()
	with pytest.raises(TypeError):
		snapshot.bindings["other"] = snapshot.bindings["echo"]  # type: ignore[index]


def test_concurrent_reads_are_consistent_during_catalog_changes() -> None:
	registry = ToolRegistry()
	registry.register_external_tools("server-a", [_external("one")], backend=FakeBackend("server-a"))
	stop = threading.Event()
	errors: list[BaseException] = []

	def reader() -> None:
		try:
			while not stop.is_set():
				snapshot = registry.snapshot()
				for binding in snapshot.bindings.values():
					assert binding.generation == snapshot.generation
					assert snapshot.resolve(binding.model_name) is binding
		except BaseException as error:  # surfaced by the assertion below
			errors.append(error)

	threads = [threading.Thread(target=reader) for _ in range(4)]
	for thread in threads:
		thread.start()
	try:
		for index in range(60):
			registry.replace_provider_catalog(
				"server-a",
				[ToolDefinition.from_provider_payload(_external(f"tool-{index}"), provider_id="server-a")],
				backend=FakeBackend("server-a"),
			)
	finally:
		stop.set()
		for thread in threads:
			thread.join(5)
	assert not errors


def test_refresh_does_not_redirect_an_already_resolved_binding() -> None:
	registry = ToolRegistry()
	registry.register_external_tools("server-a", [_external()], backend=FakeBackend("server-a", "old"))
	inflight = registry.snapshot()
	registry.replace_provider_catalog(
		"server-a",
		[ToolDefinition.from_provider_payload(_external(), provider_id="server-a")],
		backend=FakeBackend("server-a", "new"),
	)
	executor = tools_module.ToolExecutor(
		registry,
		policy=tools_module.DefaultToolPermissionPolicy(approved_provider_ids=frozenset({"server-a"})),
	)
	old_result = executor.execute(
		ToolCall(name="mcp_server-a__lookup", arguments={"key": "x"}, id="old"),
		snapshot=inflight,
	)
	new_result = executor.execute(
		ToolCall(name="mcp_server-a__lookup", arguments={"key": "x"}, id="new"),
	)
	assert old_result.text == "old"
	assert new_result.text == "new"
	assert not hasattr(inflight.require("mcp_server-a__lookup"), "invoke")


def test_provider_disable_revokes_dispatch_through_an_old_snapshot() -> None:
	backend = FakeBackend("server-a")
	registry = ToolRegistry()
	registry.register_external_tools("server-a", [_external()], backend=backend)
	old_snapshot = registry.snapshot()
	registry.set_provider_available("server-a", False)
	started: list[bool] = []
	assert registry.dispatch_if_available("server-a", "mcp:server-a:lookup", lambda: started.append(True)) is False
	assert started == []
	assert old_snapshot.resolve("mcp_server-a__lookup") is not None


def test_catalog_refresh_does_not_reenable_disabled_provider() -> None:
	registry = ToolRegistry()
	registry.register_external_tools("server-a", [_external("one")], backend=FakeBackend("server-a"))
	old_snapshot = registry.snapshot()
	registry.set_provider_available("server-a", False)
	registry.replace_provider_catalog(
		"server-a",
		[ToolDefinition.from_provider_payload(_external("two"), provider_id="server-a")],
		backend=FakeBackend("server-a"),
	)
	executor = tools_module.ToolExecutor(
		registry,
		policy=tools_module.DefaultToolPermissionPolicy(approved_provider_ids=frozenset({"server-a"})),
	)
	assert not executor.execute(ToolCall(name="mcp_server-a__lookup", arguments={}), snapshot=old_snapshot).ok
	assert not executor.execute(ToolCall(name="mcp_server-a__two", arguments={"key": "x"})).ok
	registry.set_provider_available("server-a", True)
	assert executor.execute(ToolCall(name="mcp_server-a__two", arguments={"key": "x"})).ok


def test_registry_exposes_no_direct_execution_bypass() -> None:
	registry = ToolRegistry()
	assert not callable(getattr(registry, "execute", None))


def test_removed_tool_cannot_be_invoked_by_a_new_snapshot() -> None:
	registry = ToolRegistry()
	registry.register_tool(_native())
	registry.unregister("echo")
	assert registry.snapshot().resolve("echo") is None
	with pytest.raises(tools_module.UnknownToolError):
		registry.snapshot().require("echo")
