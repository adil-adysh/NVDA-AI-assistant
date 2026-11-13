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
	assert registry.dispatch_if_available("server-a", "mcp:server-a:lookup", 1, lambda: started.append(True)) is False
	assert started == []
	assert old_snapshot.resolve("mcp_server-a__lookup") is not None


def test_unregister_then_reuse_tool_id_does_not_reactivate_old_binding() -> None:
	calls: list[str] = []
	registry = ToolRegistry()
	tool_id = "native:reusable"
	definition_a = ToolDefinition(
		name="reusable",
		description="old binding",
		tool_id=tool_id,
		executor=lambda arguments: calls.append("A") or "old",
	)
	registry.register(definition_a)
	snapshot_a = registry.snapshot()
	assert registry.unregister(tool_id)
	definition_b = ToolDefinition(
		name="reusable",
		description="new binding",
		tool_id=tool_id,
		executor=lambda arguments: calls.append("B") or "new",
	)
	registry.register(definition_b)
	policy = tools_module.DefaultToolPermissionPolicy(approved_tool_ids=frozenset({tool_id}))
	executor = tools_module.ToolExecutor(registry, policy=policy)

	old_result = executor.execute(ToolCall(name="reusable", arguments={}), snapshot=snapshot_a)
	new_result = executor.execute(ToolCall(name="reusable", arguments={}))

	assert not old_result.ok
	assert old_result.error_category == "permission_denied"
	assert new_result.ok
	assert new_result.text == "new"
	assert calls == ["B"]


@pytest.mark.parametrize("transition", ["tool", "provider"])
def test_reenable_does_not_reactivate_pre_disable_binding(transition: str) -> None:
	calls: list[str] = []
	registry = ToolRegistry()
	tool_id = "mcp:server-a:lookup"
	registry.register_external_tools(
		"server-a",
		[_external()],
		backend=type("Backend", (), {"provider_id": "server-a", "execute": lambda self, *args: calls.append("old") or "old"})(),
	)
	old_snapshot = registry.snapshot()
	if transition == "tool":
		registry.set_tool_available(tool_id, False)
		registry.set_tool_available(tool_id, True)
	else:
		registry.set_provider_available("server-a", False)
		registry.set_provider_available("server-a", True)
	new_result = tools_module.ToolExecutor(
		registry,
		policy=tools_module.DefaultToolPermissionPolicy(approved_provider_ids=frozenset({"server-a"})),
	).execute(ToolCall(name="mcp_server-a__lookup", arguments={"key": "x"}), snapshot=old_snapshot)
	assert not new_result.ok
	assert new_result.error_category == "permission_denied"
	assert calls == []


def test_atomic_catalog_refresh_keeps_existing_incarnation_and_revokes_removed_one() -> None:
	calls: list[str] = []
	registry = ToolRegistry()
	backend_a = type("Backend", (), {"provider_id": "server-a", "execute": lambda self, d, a, c: calls.append(f"A:{d.name}") or "A"})()
	registry.register_external_tools("server-a", [_external("keep"), _external("remove")], backend=backend_a)
	old_snapshot = registry.snapshot()
	backend_b = type("Backend", (), {"provider_id": "server-a", "execute": lambda self, d, a, c: calls.append(f"B:{d.name}") or "B"})()
	registry.replace_provider_catalog(
		"server-a",
		[
			ToolDefinition.from_provider_payload(_external("keep"), provider_id="server-a"),
			ToolDefinition.from_provider_payload(_external("new"), provider_id="server-a"),
		],
		backend=backend_b,
	)
	executor = tools_module.ToolExecutor(
		registry,
		policy=tools_module.DefaultToolPermissionPolicy(approved_provider_ids=frozenset({"server-a"})),
	)
	keep = executor.execute(ToolCall(name="mcp_server-a__keep", arguments={"key": "x"}), snapshot=old_snapshot)
	removed = executor.execute(ToolCall(name="mcp_server-a__remove", arguments={"key": "x"}), snapshot=old_snapshot)
	assert keep.ok and keep.text == "A"
	assert not removed.ok
	assert removed.error_category == "permission_denied"
	assert calls == ["A:mcp_server-a__keep"]


def test_concurrent_dispatch_and_unregister_reregister_never_revives_old_binding() -> None:
	calls: list[str] = []
	registry = ToolRegistry()
	tool_id = "native:race"
	registry.register(
		ToolDefinition(name="race", description="A", tool_id=tool_id, executor=lambda args: calls.append("A") or "A")
	)
	old_snapshot = registry.snapshot()
	policy = tools_module.DefaultToolPermissionPolicy(approved_tool_ids=frozenset({tool_id}))
	executor = tools_module.ToolExecutor(registry, policy=policy)
	start = threading.Event()
	finished = threading.Event()
	old_results = []

	def dispatch_loop() -> None:
		start.wait()
		for _ in range(100):
			old_results.append(executor.execute(ToolCall(name="race", arguments={}), snapshot=old_snapshot))
		finished.set()

	worker = threading.Thread(target=dispatch_loop)
	worker.start()
	start.set()
	assert registry.unregister(tool_id)
	registry.register(
		ToolDefinition(name="race", description="B", tool_id=tool_id, executor=lambda args: calls.append("B") or "B")
	)
	assert finished.wait(2)
	worker.join(2)
	count_after_revocation = len(calls)
	for _ in range(20):
		assert not executor.execute(ToolCall(name="race", arguments={}), snapshot=old_snapshot).ok
	assert len(calls) == count_after_revocation
	assert all(result.ok or result.error_category == "permission_denied" for result in old_results)
	assert "B" not in calls


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
