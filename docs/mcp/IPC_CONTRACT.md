# MCP manager worker IPC contract (version 1)

This is the JSON-lines contract between the private CPython worker and its
owned Rust `rmcp` manager. It is separate from the NVDA UI host command/event
pipes. Python remains the authority for schemas, permissions, budgets and
conversation state.

## Framing and common rules

- One UTF-8 JSON object per line, terminated by LF. Maximum command and reply
  frame: 1 MiB including serialized JSON bytes (excluding LF).
- Every command carries a unique `id` of 1–128 bytes. The manager retains a
  bounded 10,000-entry recent-ID cache; duplicate recent IDs are rejected and
  an evicted old ID may be reused. The Python client uses UUID request IDs.
- Replies carry the same `id`. Commands can execute concurrently; responses
  can arrive out of order. A client correlates by ID. Events have an `event`
  field and no command ID. Manager broadcast lag or worker-local queue overflow
  yields `resync_required`.
- The manager admits at most 32 ordinary commands and 8 control commands by
  default. Control capacity is separate, so status, cancellation, disconnect
  and shutdown remain admissible when ordinary work is saturated. The optional
  `NVDA_MCP_MAX_ACTIVE_COMMANDS` process setting changes the ordinary limit;
  `ManagerConfig` clamps it to 1–128. Saturation returns a `capacity` error
  without launching work.
- Successful `hello` negotiation is required before operational commands. It
  is protocol compatibility, not authentication. The manager is trusted
  through its worker-owned process boundary.
- Stdio EOF and explicit shutdown fence launches, cancel sessions, allow a
  bounded drain, then abort leftover command tasks. MCP protocol messages,
  transport and lifecycle use the official `rmcp` SDK; this JSONL framing is
  only the private worker IPC.

## Operations

| Operation | Request fields | Successful reply |
|---|---|---|
| `hello` | `protocol_version: 1` | `ok`, supported version, manager name and session ID |
| `connect_stdio` | `server_id`, `executable`, `args`, optional string `env` map | connection transport and negotiated protocol |
| `connect_http` | `server_id`, `url`, optional `auth_token` | connection transport and negotiated protocol |
| `status` | — | connected servers and catalog generation |
| `list_tools` | `server_id` | complete SDK tool definitions including JSON input schema and identity/generation values |
| `invoke` | `server_id`, `manager_session_id`, `server_incarnation`, `catalog_generation`, exact `tool_name`, JSON object `arguments`, `timeout_ms`, optional `tool_call_id` | source tool identity, content blocks, structured content, metadata and tool-error classification |
| `cancel` | `target_id` | whether cancellation was requested |
| `disconnect` | `server_id` | session removed and transport cancelled |
| `shutdown` | — | acknowledgement followed by process exit |

The manager preserves duplicate names across servers by requiring `server_id`;
it never silently qualifies, rewrites or merges source names. Each connection
has a server incarnation and catalog generation. Tool-list changes increment
the generation and emit `tool_list_changed`. Broadcast lag emits
`resync_required`. Consumers must refresh before dispatching with a stale
catalog. Invocation requires the expected manager session, server incarnation
and catalog generation, preventing reconnects or refreshes from redirecting an
old binding.

`auth_token` is an optional ASCII bearer token for Streamable HTTP. Python
resolves it from a DPAPI-protected setting; the manager uses it only in the
HTTP Authorization header and never returns it. URLs with userinfo, query
parameters, fragments or non-loopback plaintext HTTP are rejected.

## Errors and uncertain outcomes

Errors have a stable `category`, bounded generic message and `ok: false`.
Categories distinguish invalid requests, duplicate IDs, capacity, launch,
connection, protocol/transport errors, timeout, cancellation, disconnection,
version mismatch and frame size. A timeout, cancellation or disconnect during
an invocation sets `uncertain: true`: remote side effects may already have
happened. The manager never retries calls. MCP tool-level errors remain normal
completed results with `ok: true`, `is_error: true`, `error_source: "tool"` and
returned content intact. Protocol errors do not expose server exception text
or credentials.

## Python and worker ownership

Python resolves one catalog snapshot, validates the schema, applies current
host authorization and budgets, and calls the MCP provider only after live
registry/incarnation checks. The private worker owns one lazily started manager
process. Worker restart does not replay invocation jobs. Python keeps exact
source tool names and tool-call IDs; results pass the existing bounded result
normalization and conversation persistence path.

The command pipe carries bounded requests/replies, health, cancellation and
shutdown. Manager notifications are kept on a separate event queue. Worker
local queue overflow now emits a resync marker. Python polls the queue off the
NVDA event thread. Tool-list changes trigger a bounded per-server refresh;
queue overflow or a failed/closed notification stream triggers manager-status
resynchronization, retiring disconnected catalogs and refreshing active ones.
The application stops this poller before worker shutdown. If a list generation
changes while the Rust manager is fetching/serializing tools, it returns
`stale_catalog`; Python retries at most three times before surfacing a bounded
refresh error.

Rust fetches `tools/list` one RMCP page at a time instead of calling the SDK's
unbounded `list_all_tools()` accumulator. It checks cumulative tool count and
serialized catalog bytes after each page, rejects repeated cursors, and caps
the page count at 64. RMCP transport limits apply to each message; the
manager's cumulative catalog limit is enforced independently.

The Rust manager forwards the SDK's input schemas without changing keywords.
At registration time the Python MCP catalog adapter may remove a Draft 7
`$schema` marker only after checking that the schema uses constraints with
matching semantics in the supported core validator. Known untranslated Draft 7
assertions and tuple-array `items` fail closed. The core validator itself
continues to reject legacy dialect declarations.
