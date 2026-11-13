# Tool system architecture

Status: implemented (T01–T06). Scope: the Python tool foundation inside the
NVDA add-on. The Rust MCP manager is deliberately **not** part of this
milestone; this document defines the boundary it will plug into.

## 1. Layers

```text
WebView (non-authoritative UI)
   │  chat submission event
   ▼
ui/adapter.py ── resolves one ToolCatalogSnapshot on the chat worker thread
   ▼
service/chat/coordinator.py ── conversation fencing, generation commits
   ▼
service/llm.py ── provider request → tool loop (bounded) → provider request
   ▼
tools/executor.py ── validate · authorize · bound · normalize · diagnose
   ▼
tools/provider.py ── ToolProvider backend (native now, MCP client later)
```

The Python application/service layer is authoritative for the enabled tool
catalog. The WebView and host renderer never define tools; `ui/adapter.py`
passes the registry instance it received from the presenter and resolves the
snapshot itself. No NVDA main-thread work is added: the snapshot is resolved on
the existing chat worker thread, and handlers run off the main thread.

## 2. Canonical tool definition (`tools/definition.py`)

`ToolDefinition` is frozen metadata:

| Field | Meaning |
|---|---|
| `tool_id` | stable internal identity (`native:get_time`, `mcp:<provider>:<original>`) |
| `name` | model-visible name (validated/namespaced by the registry) |
| `provider_tool_name` | original name supplied by the provider |
| `provider_id`, `source` | origin (`native` or `mcp`) |
| `description`, `display_title` | model-visible description and optional UI title |
| `input_schema` | complete JSON Schema (object root) |
| `output_schema` | optional JSON Schema for structured output |
| `annotations` | MCP-style hints plus the original payload |
| `metadata` | provider-neutral extension data |
| `available` | per-tool availability flag |

Execution callables are accepted by the constructor for compatibility but are
stripped from definitions stored in catalog snapshots; the registry keeps them
in its own entries/bindings. `ToolDefinition.from_provider_payload()` parses a
normalized external tool description (the shape the future Rust manager will
forward). Provider-supplied names, descriptions, annotations and metadata are
stored as data only and never consulted for authorization.

## 3. Registry lifecycle (`tools/registry.py`)

All mutations take an `RLock` and publish a new immutable
`ToolCatalogSnapshot`. Reads use the published snapshot without locking.

Operations:

- `register` / `register_tool` — one definition, optional handler/backend.
- `register_provider_tools` — several tools from one provider, one commit.
- `register_external_tools` — registry-normalized provider payloads.
- `replace_provider_catalog` — build + validate the replacement first, then
  swap atomically. A failure leaves the previous catalog and generation intact.
- `unregister` / `unregister_provider` — removed tools vanish from new
  snapshots; retained bindings preserve identity but live revocation prevents
  new dispatch after removal.
- `update` — replace metadata/handler without changing `tool_id`.
- `set_provider_available` / `set_tool_available` — hide without losing identity.
- `get_enabled_definitions`, `get_definitions` (compatibility wire dicts),
  `get_tool_names`, `snapshot`, `resolve`.

Availability changes and unregister operations also revoke dispatch against
retained snapshots. `ToolExecutor` checks the live registry gate immediately
before starting a handler, so a snapshot preserves identity across a catalog
refresh but cannot override a live provider/tool disablement. Policy can be
replaced through the executor; replacement denies newly disallowed calls and
signals matching active calls to cancel cooperatively. Re-enabling availability
does not reinstate an approval removed from the current policy.

### Naming

Model-facing names must match `^[A-Za-z0-9_-]{1,64}$`.

- Native tools keep their declared name; an invalid name is an error, not a
  silent rename.
- External tools become `mcp_<provider>__<original>` with deterministic
  sanitisation and truncation hash. Per-provider sanitisation collisions append
  a deterministic SHA-1 suffix derived from the stable `tool_id`.
- Cross-identity collisions raise `ToolNameConflictError`.
- `ToolBinding.original_name` / `ToolDefinition.provider_tool_name` keep the
  reversible mapping to the provider's original name.

### Generations and snapshot binding

`ToolCatalogSnapshot.generation` increments on every publish; each
`ToolBinding` records the generation it was created in. A chat turn resolves
one snapshot (`ui/adapter.py` → `ChatCoordinator` → `ProviderLLMService` →
`ToolExecutor`) and every tool call for that turn resolves through it.

Consequence: a catalog refresh during a turn cannot redirect an authorized call
to a different tool under the same model-facing name. The in-flight snapshot
holds the old handler/backend; new requests see the new snapshot and cannot
invoke removed tools. This is covered by
`tests/tools/test_registry.py::test_refresh_does_not_redirect_an_already_resolved_binding`
and `tests/tools/test_provider_contract.py`.

## 4. Execution coordinator (`tools/executor.py`, `tools/budget.py`)

`ToolExecutor` is the single coordination point and keeps a synchronous API:

1. Resolve the binding in the turn snapshot (or the current snapshot).
2. Refuse malformed JSON (`ToolCall.parse_error`) and non-object arguments.
3. Validate arguments against `input_schema`; no execution on failure.
4. Apply the permission policy.
5. Enforce the budget (turn duration, call count, per-call timeout).
6. Check cancellation and live provider/tool availability before starting.
7. Run the backend on a daemon thread and join with a deadline, polling for
   cancellation every 20 ms.
8. Normalize the outcome into `ToolExecutionResult` (identity, call id,
   content blocks, structured content, category, duration, correlation,
   cancellation/timeout/uncertainty) and bound its complete persisted envelope.
9. Update in-process diagnostics counters.

Backends return either a JSON value, text, `ToolContentBlock`, or a
`ToolExecutionResult`. A returned `ToolExecutionResult(ok=False)` is treated as
a **tool-level** error (the future MCP `isError=true` case), never as success.
At most eight tool handler threads may be outstanding process-wide. Timeout or
cancellation signals the backend and returns promptly, but the admission slot
is retained until the handler really exits; an exhausted gate returns a
bounded budget error without starting another thread.

### Budgets

`ToolExecutionBudget` defaults: 5 iterations, 20 tool calls, 1 parallel call
(reserved; execution is serial by default), 30 s per call, 300 s per turn,
20 000 result characters. The existing five-step loop cap is preserved. When the
iteration limit is reached, outstanding tool calls receive `budget_exceeded`
results and a final assistant message, so the persisted transcript stays valid.

## 5. Provider interface (`tools/provider.py`)

```python
class ToolProvider(Protocol):
    provider_id: str
    def execute(self, definition, arguments, context: ToolCallContext) -> object: ...
```

`NativeToolBackend` adapts a callable; a future `McpToolProvider` will adapt the
Rust manager's request/response protocol. `ToolCallContext` carries identity,
correlation, timeout and a cancellation probe. Backends raise
`ToolProviderError` for transport/protocol failures (with `uncertain=True` when
the request may have been delivered) and return `ToolExecutionResult(ok=False)`
for tool-level errors. This preserves the MCP distinction between protocol
errors and tool results with `isError=true`.

## 6. Error model (`tools/errors.py`, `core/tooling.py`)

| Category | Source | Retry-safe | Meaning |
|---|---|---|---|
| `invalid_arguments` | host | yes | malformed JSON or schema violation; tool never ran |
| `unknown_tool` | host | no | not in the resolved snapshot |
| `permission_denied` | host | no | host policy denied |
| `provider_failure` | provider | only if `uncertain=False` | transport/protocol failure |
| `execution_error` | tool | yes | tool raised or reported `isError` |
| `timeout` | host | no (uncertain) | deadline exceeded; termination unconfirmed |
| `cancelled` | host | no (uncertain) | user/request cancellation |
| `budget_exceeded` | host | no | iteration/call/turn budget |
| `schema_error` | host | n/a | reserved for registration-time schema failures |

`uncertain=True`/`termination_confirmed=False` means the tool may have run. The
code never retries automatically. Model-visible error text is bounded, control
characters are collapsed, and Authorization/API-key/token patterns are
redacted; structured category/source/correlation fields remain available.

## 7. Cancellation semantics

- Cancellation is request-scoped via the existing `CancellationToken` /
  context variable.
- A call cancelled before dispatch returns `cancelled`.
- A call cancelled (or timed out) while running signals its cooperative probe,
  returns promptly with
  `termination_confirmed=False`; the daemon thread cannot be force-killed and
  may finish its side effects later.
- `ProviderLLMService` re-checks cancellation between calls, so a stop skips
  remaining calls and aborts the turn exactly as before.
- Conversation-generation fencing is unchanged: a turn whose conversation
  changed while tools were running is discarded, not committed.

## 8. Tool permission policy (`tools/policy.py`)

`DefaultToolPermissionPolicy` allows:

1. tools whose stable `tool_id` is explicitly approved by the host;
2. all tools of an explicitly approved provider;
3. **native** tools whose host-authored definition is annotated
   `read_only_hint=True`.

Everything else is denied. External annotations (`readOnlyHint`,
`destructiveHint`, titles, descriptions) are ignored for authorization. The
executor can replace its current policy through a synchronized boundary, and
policy changes revoke and signal affected active operations. The plugin
composition root uses the deny-by-default policy; tests may inject
`AllowAllToolPermissionPolicy`.

Every published binding also carries a registry-assigned incarnation. Explicit
disablement, removal, or provider revocation advances the live incarnation;
dispatch checks provider availability, revocation, and binding incarnation
atomically immediately before starting the worker thread. This prevents a
saved snapshot from becoming valid again if the same stable `tool_id` is later
registered for a different handler. Ordinary catalog refresh retains the
incarnation for retained IDs, so already-authorized work stays bound to its
original handler rather than being redirected.

## 9. JSON Schema support (`tools/schema.py`)

The validator is dependency-free on purpose. `jsonschema`'s `rpds-py`
transitive dependency is a native wheel that would have to be vendored and
loaded inside NVDA; that packaging risk is out of scope and would violate the
"no unnecessary dependencies" constraint.

Supported (and preserved) keywords include: `type` (string or list), `properties`,
`patternProperties`, `required`, `additionalProperties` (bool or schema),
`items`/`prefixItems`, `minItems`/`maxItems`/`uniqueItems`, `contains`,
`minContains`/`maxContains`, `propertyNames`, `dependentRequired`,
`dependentSchemas`, `if`/`then`/`else`, `enum`, `const`,
`$defs`/`definitions` + local `$ref`, `allOf`/`anyOf`/`oneOf`/`not`,
`minLength`/`maxLength`/`pattern`, numeric bounds and `multipleOf`,
`minProperties`/`maxProperties`, `title`/`description`/`format`/`default`.
Unknown keywords are preserved verbatim. Non-local `$ref` and recursive `$ref`
cycles are rejected with actionable errors. Structural validation rejects bad
keyword shapes; argument validation produces bounded, path-addressed
`SchemaViolation`s. Input schemas must be object-rooted; output schemas may be
any JSON type. Serialization uses sorted compact JSON
(`serialize_schema`/`schema_fingerprint`) for deterministic fingerprints, and
schema, metadata and annotation data are deeply frozen at definition boundaries.
Serialization explicitly thaws copies. Unsupported assertion vocabularies such
as `unevaluatedProperties` are rejected rather than silently ignored. Regex
patterns use a bounded safe subset; nested repetition, backreferences and
lookarounds are rejected, and candidate strings are capped. `format` remains
annotation-only under the default Draft 2020-12 vocabulary. Integral floating
point values satisfy the JSON Schema `integer` type, and `multipleOf` uses
base-10 decimal arithmetic.

## 10. Conversation history representation

- `Part.text` on a `tool_result` part is the bounded, provider-safe text sent
  back to the model.
- `Part.tool_result` stores the structured `ToolExecutionResult.to_dict()`
  envelope (outcome, category, structured content, duration, correlation,
  uncertainty). It is persisted and reloadable.
- `Part.tool_call_id` is now persisted too, fixing correlation loss on reload.
- Provider adapters use `Part.text` when present; only legacy parts without
  text fall back to JSON. Image/audio/resource content is represented by
  explicit placeholders (`[image result omitted: …]`), never disguised as the
  real payload. `structured_content` is retained internally.
- On the iteration limit, outstanding assistant `tool_calls` are closed with
  `budget_exceeded` tool results before a final assistant message, so the
  transcript is always valid for the next request.

## 11. Future Rust MCP integration points

The Rust manager (not implemented here) should:

1. Own transport, discovery and `tools/list` / `tools/call`.
2. Hand normalized tool descriptions to `ToolDefinition.from_provider_payload`
   (or the equivalent dict) via `ToolRegistry.register_external_tools(...)` /
   `replace_provider_catalog(...)`, one provider id per server.
3. Implement `ToolProvider.execute(definition, arguments, context)` in a small
   Python adapter that calls the Rust client, and register it as the provider
   backend.
4. Map protocol/transport errors to `ToolProviderError(uncertain=…)`; return
   `ToolExecutionResult(ok=False, error_source="tool")` for `isError=true`
   results.
5. Call `set_provider_available(provider_id, False)` on disconnect and
   `unregister_provider` on removal.
6. Never rely on server metadata for authorization; the host approval sets are
   the only authority. The host should add approvals keyed by stable `tool_id`
   (which includes the provider id and original tool name).

No core rewrite is required for this: identity, naming, snapshots, validation,
policy, budgeting, cancellation and result classification are already
provider-neutral.

## 12. Security and concurrency review

- **Thread affinity**: no NVDA object-model access added. Snapshot resolution
  happens on the chat worker; tool handlers run on daemon threads (or the chat
  worker) — never the NVDA main thread.
- **Authorization**: deny-by-default; external metadata untrusted; policy
  replacement revokes newly unauthorized work; approvals are host-owned.
- **Data exposure**: bounded results and errors; secret redaction; unsupported
  content is marked, not rendered; no tool output can change policy.
- **Races**: registry state behind one lock; immutable snapshots published by
  single reference assignment; generation recorded per binding; live dispatch
  checks make disable/removal effective against retained snapshots (tested).
- **Runaway work**: per-call timeout, turn timeout, call and iteration caps;
  timers poll cancellation; no automatic retries.
- **Persistence**: envelopes are JSON-safe and round-trip through both the JSON
  repository and the worker persistence lane.

## 13. Remaining risks

1. Timeout/cancellation cannot kill an in-process native handler; a hung
   handler keeps one of eight process-wide slots occupied. It is reported as
   unconfirmed and never retried, but it may still produce side effects.
2. No permission UI yet: external tools cannot be approved through the UI, so
   they stay denied until a future host-surface approval flow lands.
3. The custom JSON Schema implementation intentionally rejects unevaluated and
   dynamic-reference assertions and ignores `format` semantics by default; it
   does not support external/remote or recursive `$ref`. An MCP server relying
   on these needs schema pre-resolution or a supported schema profile.
4. Parallel tool execution is modelled in `ToolExecutionBudget` but executes
   serially by design; enabling it needs per-tool side-effect analysis.
5. `ToolDefinition` keeps a legacy `executor` field for constructor
   compatibility; handlers are stripped from snapshots, but callers can still
   construct a definition with a callback embedded.
