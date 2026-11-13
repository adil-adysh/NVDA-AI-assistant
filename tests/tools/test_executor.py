# -*- coding: utf-8 -*-
"""Structured execution: classification, validation, policy, time and bounds."""
from __future__ import annotations

import importlib
import threading
import time


from tests.support import ADDON_ROOT, register_package

NAMESPACE = "tool_executor_testpkg"
register_package(NAMESPACE, ADDON_ROOT)
tools_module = importlib.import_module(f"{NAMESPACE}.tools")
core = importlib.import_module(f"{NAMESPACE}.core.tooling")

ToolDefinition = tools_module.ToolDefinition
ToolRegistry = tools_module.ToolRegistry
ToolExecutor = tools_module.ToolExecutor
ToolAnnotations = tools_module.ToolAnnotations
ToolCall = core.ToolCall
ToolExecutionResult = core.ToolExecutionResult
ToolContentBlock = core.ToolContentBlock


def _registry(handler, *, name="echo", read_only=True, **kwargs) -> ToolRegistry:
	registry = ToolRegistry()
	registry.register_tool(
		ToolDefinition(
			name=name,
			description="echo tool",
			input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
			if kwargs.pop("requires_text", False)
			else {"type": "object", "properties": {}},
			annotations=ToolAnnotations(read_only_hint=read_only),
			executor=handler,
			**kwargs,
		)
	)
	return registry


def _call(name="echo", arguments=None, call_id="call-1", parse_error=None) -> ToolCall:
	return ToolCall(name=name, arguments=arguments or {}, id=call_id, parse_error=parse_error)


def test_success_returns_structured_text_result() -> None:
	registry = _registry(lambda arguments: "2026-11-13T10:00:00")
	executor = ToolExecutor(registry)
	result = executor.execute(_call())
	assert result.ok
	assert result.text == "2026-11-13T10:00:00"
	assert result.tool_call_id == "call-1"
	assert result.tool_id == "native:echo"
	assert result.error_category is None
	assert result.duration_ms >= 0


def test_structured_value_preserves_json_content() -> None:
	registry = _registry(lambda arguments: {"value": 42, "nested": [1, 2, 3]})
	result = ToolExecutor(registry).execute(_call())
	assert result.ok
	assert result.structured_content == {"value": 42, "nested": [1, 2, 3]}
	assert result.content[0].type == "json"
	assert '"value":42' in result.text


def test_tool_exception_is_classified_as_failure() -> None:
	def boom(arguments):
		raise RuntimeError("disk unavailable")

	result = ToolExecutor(_registry(boom)).execute(_call())
	assert not result.ok
	assert result.error_category == "execution_error"
	assert result.error_source == "tool"
	assert "disk unavailable" in (result.error_message or "")
	assert result.structured_content is None


def test_invalid_arguments_never_execute_the_tool() -> None:
	calls: list[dict] = []
	registry = _registry(lambda arguments: calls.append(arguments) or "ran", requires_text=True)
	result = ToolExecutor(registry).execute(_call(arguments={}))
	assert not result.ok
	assert result.error_category == "invalid_arguments"
	assert "$.text" in (result.error_message or "")
	assert calls == []


def test_malformed_json_arguments_never_execute_the_tool() -> None:
	calls: list[dict] = []
	registry = _registry(lambda arguments: calls.append(arguments) or "ran")
	result = ToolExecutor(registry).execute(_call(parse_error="malformed JSON arguments: Expecting ','"))
	assert not result.ok
	assert result.error_category == "invalid_arguments"
	assert "malformed JSON" in (result.error_message or "")
	assert calls == []


def test_unknown_tool_is_classified() -> None:
	result = ToolExecutor(ToolRegistry()).execute(_call(name="missing"))
	assert not result.ok
	assert result.error_category == "unknown_tool"
	assert "Unknown tool: missing" in (result.error_message or "")
	assert result.tool_call_id == "call-1"


def test_permission_denied_by_default_for_sensitive_native_tool() -> None:
	calls: list[dict] = []
	registry = _registry(lambda arguments: calls.append(arguments) or "ran", read_only=False)
	result = ToolExecutor(registry).execute(_call())
	assert not result.ok
	assert result.error_category == "permission_denied"
	assert calls == []


def test_approved_tool_can_execute() -> None:
	calls: list[dict] = []
	registry = _registry(lambda arguments: calls.append(arguments) or "ran", read_only=False)
	policy = tools_module.DefaultToolPermissionPolicy(approved_tool_ids=frozenset({"native:echo"}))
	result = ToolExecutor(registry, policy=policy).execute(_call())
	assert result.ok
	assert calls == [{}]


def test_timeout_is_unconfirmed_and_not_retried() -> None:
	finished = threading.Event()

	def slow(arguments):
		try:
			time.sleep(0.3)
			return "late"
		finally:
			finished.set()

	registry = _registry(slow)
	executor = ToolExecutor(
		registry,
		budget=tools_module.ToolExecutionBudget(call_timeout_seconds=0.05, turn_timeout_seconds=5.0),
	)
	result = executor.execute(_call())
	assert not result.ok
	assert result.error_category == "timeout"
	assert result.timed_out
	assert result.uncertain
	assert not result.termination_confirmed
	assert finished.wait(1)


def test_cancellation_before_execution() -> None:
	token = importlib.import_module(f"{NAMESPACE}.core.cancellation").CancellationToken()
	token.cancel()
	calls: list[dict] = []
	registry = _registry(lambda arguments: calls.append(arguments) or "ran")
	result = ToolExecutor(registry).execute(_call(), cancellation_token=token)
	assert not result.ok
	assert result.error_category == "cancelled"
	assert result.cancelled
	assert not result.termination_confirmed
	assert calls == []


def test_cancellation_during_execution_returns_promptly() -> None:
	token = importlib.import_module(f"{NAMESPACE}.core.cancellation").CancellationToken()
	finished = threading.Event()

	def slow(arguments):
		try:
			time.sleep(0.5)
			return "late"
		finally:
			finished.set()

	registry = _registry(slow)
	executor = ToolExecutor(
		registry,
		budget=tools_module.ToolExecutionBudget(call_timeout_seconds=2.0, turn_timeout_seconds=5.0),
	)
	threading.Timer(0.05, token.cancel).start()
	started = time.monotonic()
	result = executor.execute(_call(), cancellation_token=token)
	assert time.monotonic() - started < 0.4
	assert result.error_category == "cancelled"
	assert not result.termination_confirmed
	assert finished.wait(1)


def test_uncertain_provider_failure() -> None:
	class Backend:
		provider_id = "server-a"

		def execute(self, definition, arguments, context):
			raise tools_module.ToolProviderError("connection lost after send", uncertain=True)

	registry = ToolRegistry()
	registry.register_external_tools(
		"server-a",
		[{"name": "write", "inputSchema": {"type": "object", "properties": {}}}],
		backend=Backend(),
	)
	policy = tools_module.DefaultToolPermissionPolicy(approved_provider_ids=frozenset({"server-a"}))
	result = ToolExecutor(registry, policy=policy).execute(_call(name="mcp_server-a__write"))
	assert not result.ok
	assert result.error_category == "provider_failure"
	assert result.uncertain
	assert not result.termination_confirmed


def test_tool_level_error_result_is_not_success() -> None:
	class Backend:
		provider_id = "server-a"

		def execute(self, definition, arguments, context):
			return ToolExecutionResult(
				tool_name=definition.name,
				ok=False,
				error_category="execution_error",
				error_message="resource does not exist",
				error_source="tool",
			)

	registry = ToolRegistry()
	registry.register_external_tools(
		"server-a",
		[{"name": "read", "inputSchema": {"type": "object", "properties": {}}}],
		backend=Backend(),
	)
	result = ToolExecutor(
		registry,
		policy=tools_module.DefaultToolPermissionPolicy(approved_provider_ids=frozenset({"server-a"})),
	).execute(_call(name="mcp_server-a__read"))
	assert not result.ok
	assert result.error_source == "tool"
	assert "resource does not exist" in (result.error_message or "")


def test_large_output_is_bounded() -> None:
	registry = _registry(lambda arguments: "x" * 50_000)
	result = ToolExecutor(registry).execute(_call())
	assert result.ok
	assert len(result.text) <= core.MAX_TOOL_RESULT_CHARS
	assert result.text.endswith("[truncated]")


def test_unknown_content_kinds_are_explicitly_marked() -> None:
	image = ToolContentBlock(type="image", data="AAAA", mime_type="image/png")
	audio = ToolContentBlock(type="audio", data="BBBB", mime_type="audio/wav")
	resource = ToolContentBlock(type="resource", uri="file:///secret.txt")
	rendered = "\n".join(block.to_model_text() for block in (image, audio, resource))
	assert "image result omitted" in rendered
	assert "audio result omitted" in rendered
	assert "resource result omitted" in rendered
	assert "AAAA" not in rendered


def test_tool_call_budget_produces_one_result_per_call() -> None:
	calls: list[dict] = []
	registry = _registry(lambda arguments: calls.append(arguments) or "ran")
	executor = ToolExecutor(
		registry,
		budget=tools_module.ToolExecutionBudget(max_tool_calls=1, turn_timeout_seconds=5.0),
	)
	results = executor.execute_tool_calls([_call(call_id="1"), _call(call_id="2")])
	assert len(results) == 2
	assert results[0].ok
	assert results[1].error_category == "budget_exceeded"
	assert results[1].tool_call_id == "2"
	assert len(calls) == 1


def test_diagnostics_count_outcomes() -> None:
	registry = _registry(lambda arguments: "ok")
	executor = ToolExecutor(registry)
	executor.execute(_call())
	executor.execute(_call(name="missing", call_id="2"))
	diagnostics = executor.diagnostics()
	assert diagnostics["calls"] == 2
	assert diagnostics["successes"] == 1
	assert diagnostics["failures"] == 1
	assert diagnostics["by_category"]["unknown_tool"] == 1


def test_secrets_in_error_messages_are_redacted() -> None:
	def boom(arguments):
		raise RuntimeError("request failed with Authorization: Bearer abc.def.ghi")

	result = ToolExecutor(_registry(boom)).execute(_call())
	assert "abc.def.ghi" not in (result.error_message or "")
	assert "[redacted]" in (result.error_message or "")


def test_unapproved_external_tool_is_denied() -> None:
	class Backend:
		provider_id = "server-a"
		called = False

		def execute(self, definition, arguments, context):
			self.called = True
			return "ran"

	backend = Backend()
	registry = ToolRegistry()
	registry.register_external_tools(
		"server-a",
		[
			{
				"name": "write",
				"inputSchema": {"type": "object", "properties": {}},
				"annotations": {"readOnlyHint": True, "destructiveHint": False},
			}
		],
		backend=backend,
	)
	result = ToolExecutor(registry).execute(_call(name="mcp_server-a__write"))
	assert not result.ok
	assert result.error_category == "permission_denied"
	assert backend.called is False


def test_oversized_structured_result_is_rejected_and_envelope_is_bounded() -> None:
	registry = _registry(lambda arguments: {"payload": "x" * (256 * 1024 * 2)})
	result = ToolExecutor(registry).execute(_call())
	assert not result.ok
	assert result.error_category == "execution_error"
	assert "resource limits" in (result.error_message or "")
	assert len(__import__("json").dumps(result.to_dict()).encode("utf-8")) <= 256 * 1024
	restored = ToolExecutionResult.from_dict(result.to_dict())
	assert restored.error_category == "execution_error"


def test_oversized_media_and_excessive_content_blocks_are_rejected() -> None:
	too_large_media = ToolContentBlock(type="image", data="A" * (256 * 1024 * 2))
	media_result = ToolExecutor(_registry(lambda arguments: too_large_media)).execute(_call())
	assert not media_result.ok
	assert media_result.error_category == "execution_error"

	blocks = tuple(ToolContentBlock.text_block(str(index)) for index in range(65))
	tool_result = ToolExecutionResult(tool_name="echo", ok=True, content=blocks)
	block_result = ToolExecutor(_registry(lambda arguments: tool_result)).execute(_call())
	assert not block_result.ok
	assert block_result.error_category == "execution_error"

	metadata_result = ToolExecutionResult(
		tool_name="echo",
		ok=True,
		metadata={"payload": "x" * (256 * 1024)},
	)
	bounded_metadata = ToolExecutor(_registry(lambda arguments: metadata_result)).execute(_call())
	assert bounded_metadata.error_category == "execution_error"

	deep_value = None
	for _ in range(40):
		deep_value = [deep_value]
	deep_result = ToolExecutor(_registry(lambda arguments: deep_value)).execute(_call())
	assert deep_result.error_category == "execution_error"


def test_cyclic_structured_result_becomes_a_correlated_failure() -> None:
	cyclic = {}
	cyclic["self"] = cyclic
	result = ToolExecutor(_registry(lambda arguments: cyclic)).execute(_call(call_id="cyclic-call"))
	assert not result.ok
	assert result.tool_call_id == "cyclic-call"
	assert result.error_category == "execution_error"
	assert len(__import__("json").dumps(result.to_dict()).encode("utf-8")) <= 256 * 1024


def test_unsupported_backend_value_becomes_a_structured_failure() -> None:
	result = ToolExecutor(_registry(lambda arguments: object())).execute(_call(call_id="unsupported-call"))
	assert not result.ok
	assert result.tool_call_id == "unsupported-call"
	assert result.error_category == "execution_error"
	assert "unsupported value type" in (result.error_message or "")




def test_disabled_provider_rejects_dispatch_from_a_retained_snapshot() -> None:
	class Backend:
		provider_id = "server-a"
		called = False

		def execute(self, definition, arguments, context):
			self.called = True
			return "ran"

	backend = Backend()
	registry = ToolRegistry()
	registry.register_external_tools("server-a", [{"name": "read", "inputSchema": {"type": "object"}}], backend=backend)
	snapshot = registry.snapshot()
	registry.set_provider_available("server-a", False)
	executor = ToolExecutor(
		registry,
		policy=tools_module.DefaultToolPermissionPolicy(approved_provider_ids=frozenset({"server-a"})),
	)
	result = executor.execute(_call(name="mcp_server-a__read"), snapshot=snapshot)
	assert not result.ok
	assert result.error_category == "permission_denied"
	assert not backend.called


def test_permission_revocation_cancels_active_cooperative_backend() -> None:
	started = threading.Event()
	observed_cancel = threading.Event()
	finished = threading.Event()

	class Backend:
		provider_id = "server-a"

		def execute(self, definition, arguments, context):
			try:
				started.set()
				while not context.cancelled():
					time.sleep(0.005)
				observed_cancel.set()
				return "stopped"
			finally:
				finished.set()

	registry = ToolRegistry()
	registry.register_external_tools("server-a", [{"name": "read", "inputSchema": {"type": "object"}}], backend=Backend())
	executor = ToolExecutor(
		registry,
		policy=tools_module.DefaultToolPermissionPolicy(approved_provider_ids=frozenset({"server-a"})),
	)
	results = []
	thread = threading.Thread(target=lambda: results.append(executor.execute(_call(name="mcp_server-a__read"))))
	thread.start()
	assert started.wait(1)
	executor.set_policy(tools_module.DefaultToolPermissionPolicy())
	thread.join(1)
	assert not thread.is_alive()
	assert observed_cancel.is_set()
	assert results[0].error_category == "cancelled"
	assert not results[0].termination_confirmed
	assert finished.wait(1)


def test_provider_disable_cancels_active_cooperative_backend() -> None:
	started = threading.Event()
	observed_cancel = threading.Event()
	finished = threading.Event()

	class Backend:
		provider_id = "server-a"

		def execute(self, definition, arguments, context):
			try:
				started.set()
				while not context.cancelled():
					time.sleep(0.005)
				observed_cancel.set()
				return "stopped"
			finally:
				finished.set()

	registry = ToolRegistry()
	registry.register_external_tools("server-a", [{"name": "read", "inputSchema": {"type": "object"}}], backend=Backend())
	executor = ToolExecutor(
		registry,
		policy=tools_module.DefaultToolPermissionPolicy(approved_provider_ids=frozenset({"server-a"})),
	)
	results = []
	thread = threading.Thread(target=lambda: results.append(executor.execute(_call(name="mcp_server-a__read"))))
	thread.start()
	assert started.wait(1)
	registry.set_provider_available("server-a", False)
	thread.join(1)
	assert not thread.is_alive()
	assert observed_cancel.is_set()
	assert results[0].error_category == "cancelled"
	assert finished.wait(1)


def test_provider_reenable_does_not_restore_revoked_approval() -> None:
	class Backend:
		provider_id = "server-a"
		called = False

		def execute(self, definition, arguments, context):
			self.called = True
			return "ran"

	backend = Backend()
	registry = ToolRegistry()
	registry.register_external_tools("server-a", [{"name": "read", "inputSchema": {"type": "object"}}], backend=backend)
	snapshot = registry.snapshot()
	executor = ToolExecutor(
		registry,
		policy=tools_module.DefaultToolPermissionPolicy(approved_provider_ids=frozenset({"server-a"})),
	)
	executor.set_policy(tools_module.DefaultToolPermissionPolicy())
	registry.set_provider_available("server-a", False)
	registry.set_provider_available("server-a", True)
	result = executor.execute(_call(name="mcp_server-a__read"), snapshot=snapshot)
	assert result.error_category == "permission_denied"
	assert not backend.called


def test_timed_out_handlers_keep_global_capacity_until_they_finish() -> None:
	capacity = 8
	release = threading.Event()
	all_started = threading.Event()
	all_finished = threading.Event()
	lock = threading.Lock()
	calls = 0
	finished = 0

	def handler(arguments):
		nonlocal calls, finished
		with lock:
			calls += 1
			if calls == capacity:
				all_started.set()
		release.wait(2)
		with lock:
			finished += 1
			if finished == capacity:
				all_finished.set()
		return "done"

	registry = _registry(handler)
	budget = tools_module.ToolExecutionBudget(call_timeout_seconds=0.02, turn_timeout_seconds=5.0)
	try:
		for index in range(capacity):
			result = ToolExecutor(registry, budget=budget).execute(_call(call_id=f"stalled-{index}"))
			assert result.error_category == "timeout"
		assert all_started.wait(1)
		rejected = ToolExecutor(registry, budget=budget).execute(_call(call_id="over-capacity"))
		assert rejected.error_category == "budget_exceeded"
		assert calls == capacity
	finally:
		release.set()
	assert all_finished.wait(1)
	completed = ToolExecutor(registry, budget=budget).execute(_call(call_id="after-release"))
	assert completed.ok
	assert calls == capacity + 1
