# Tool system migration guide

This document describes what changed for existing callers and what a future MCP
provider must do. Existing behavior is preserved wherever practical; the
compatibility shims are listed explicitly.

## 1. Native tool registration

Existing code keeps working:

```python
ToolDefinition(
    name="get_time",
    description="Get the current local date and time.",
    parameters={},
    required=[],
    executor=lambda arguments: datetime.now().isoformat(),
)
```

What changed:

- `parameters`/`required` are folded into a full object-rooted
  `input_schema`. Prefer passing `input_schema` for new tools.
- `to_dict()` now serializes `input_schema` (nested schemas survive), not just
  a rebuilt `{type, properties, required}` object.
- `ToolDefinition` is immutable and deep-copies its schemas. Mutating the
  dictionary you passed in no longer affects the definition.
- An invalid name or invalid schema now raises at construction time
  (`ValueError` / `ToolSchemaError`) instead of failing later at a provider.

The default catalog lives in `tools/defaults.py`
(`register_default_tools`, `build_default_tool_definitions`) and
`plugin/factory.py` calls it. `get_time` is annotated
`read_only_hint=True`, which is what lets the deny-by-default policy allow it.

### Policies

`ToolExecutor(registry)` now uses `DefaultToolPermissionPolicy`. Native tools
without `read_only_hint=True` and all external tools are denied until the host
approves them:

```python
policy = DefaultToolPermissionPolicy(
    approved_tool_ids=frozenset({"mcp:server-a:delete"}),
    approved_provider_ids=frozenset(),
)
executor = ToolExecutor(registry, policy=policy)
```

## 2. Registry API

`ToolRegistry.register_tool(tool)` still requires an executor and still rejects
duplicates. New capabilities:

| Old | New |
|---|---|
| `register_tool` | `register`, `register_provider_tools`, `register_external_tools`, `replace_provider_catalog` |
| `get_definitions()` | kept (wire dicts); prefer `get_enabled_definitions()` / `snapshot()` |
| `get_tool_names()` | kept; returns enabled model-facing names |
| `execute(tool_call)` | deprecated compatibility path; use `ToolExecutor` for policy/timeouts |

`ToolRegistry.execute()` cannot enforce policy, budgets or timeouts and should
not be used by new code.

### Names

- Native names must be `^[A-Za-z0-9_-]{1,64}$`; invalid names raise instead of
  being silently rewritten.
- External names are `mcp_<provider>__<original>` (deterministic, reversible
  via `ToolBinding.original_name`).
- `get_tool_names()` returns model-facing names; `unregister`/`update`/
  `set_tool_available` accept either the stable `tool_id` or the current
  model-facing name.

## 3. Execution results

`tools/executor.py` no longer returns strings and no longer raises for ordinary
failures. `ToolExecutor.execute()` returns a `core.tooling.ToolExecutionResult`:

```python
result.ok                    # False for every failure
result.text                  # bounded model-visible text
result.structured_content    # any JSON value, or None
result.error_category        # invalid_arguments, unknown_tool, ...
result.tool_call_id          # correlation preserved
result.timed_out / result.cancelled
result.uncertain             # do not retry automatically
```

`core.messages.ToolExecutionResult` is now a re-export of this type. Callers
that only need the old text can use `result.text`.

`ProviderLLMService.generate_with_transcript()` gained optional `tool_catalog`
and `tracker` parameters. Existing calls without them still work; the executor
then uses the registry's current snapshot and a default budget.

`ChatCoordinator.send_message()` gained an optional `tool_catalog` parameter.
When it is supplied, the coordinator passes `tool_catalog.provider_tools()` to
the provider and the same snapshot to the executor.

## 4. UI adapter

`ui/adapter.py` no longer leaves `tool_registry` unused. The submission handler
carries the presenter's registry into the chat worker thread, resolves
`tool_registry.snapshot()` there, and passes it as `tool_catalog`. The WebView
remains presentation-only.

Tests that call `_handle_host_chat_submission` positionally are unaffected; the
new parameter is optional and appended (`tool_registry`).

## 5. Conversation history format

`Part` changes (backwards compatible on read):

- `tool_call_id` is now persisted for both tool-call and tool-result parts.
  Older saved conversations simply lack it.
- `tool_result` may hold the structured result envelope (a JSON object) rather
  than a small content dictionary. Older readers that expect a content dict
  still receive a dict; new readers can use
  `core.message_transforms.tool_result_message_from_payload`.
- Provider adapters use `Part.text` for the model-visible tool result and only
  fall back to JSON-serializing `tool_result` for legacy parts. This prevents
  the internal envelope from being sent to the model.

`build_tool_result_message(...)` is unchanged (text-only).
`build_tool_result_message_from_result(result)` is the new structured path used
by `ProviderLLMService`.

## 6. Provider adapters

OpenAI-compatible and Ollama serializers both use
`build_function_tool_definition`, which now emits the complete `input_schema`.
No adapter signature changed.

Tool-call decoding (`normalize_tool_calls`) now sets `ToolCall.parse_error` for
malformed JSON or non-object arguments. The executor refuses to run such calls
and returns `invalid_arguments`, so a provider bug can no longer silently turn
into an execution with `{}`.

## 7. Adding an external (future MCP) provider

```python
registry.register_external_tools(
    provider_id="server-a",
    payloads=[{"name": "lookup", "description": "...", "inputSchema": {...}, "outputSchema": {...}}],
    backend=my_backend,          # implements tools.provider.ToolProvider
)
```

- One `provider_id` per server; it participates in the stable `tool_id`
  (`mcp:server-a:lookup`) and in the model-facing name.
- Refresh with `replace_provider_catalog(...)`; it is atomic and leaves the
  previous catalog on failure.
- On disconnect call `set_provider_available("server-a", False)`; on removal
  call `unregister_provider("server-a")`.
- Map transport/protocol failures to `ToolProviderError(..., uncertain=...)`;
  return `ToolExecutionResult(ok=False, error_source="tool")` for tool-level
  errors.
- Server-provided annotations are untrusted; host approval is required.

## 8. Test migration

- The default policy now denies non-read-only native tools. Tests that
  construct sensitive tools must inject an approval policy or annotate the
  definition.
- Tests that assert old string results should read `result.text` and
  `result.ok`.
- New suites live in `tests/tools/`; adapter forwarding tests are appended to
  `tests/ui/test_adapter_fallback.py`.
