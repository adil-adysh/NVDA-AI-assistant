# MCP manager prototype IPC contract (version 1)

This is a feasibility contract for a future private-worker adapter. It is not
the production NVDA command/event pipe contract and the prototype is not
packaged with the add-on.

## Framing and common rules

- One UTF-8 JSON object per line, terminated by LF. Maximum command and reply
  frame: 1 MiB including serialized JSON bytes (excluding LF).
- Every command carries a unique `id` of 1–128 bytes. An ID is never reused
  during one manager process; the bounded history holds 10,000 IDs, after
  which new commands receive a capacity error. Invalid/oversized frames are
  rejected without deserializing their payload.
- Replies carry the same `id`. Commands can execute concurrently; responses
  can arrive out of order. A client correlates by ID. Events have an `event`
  field and no command ID. A broadcast overflow yields `resync_required`.
- Protocol version mismatch fails closed. Stdio EOF and explicit shutdown
  fence launches, cancel sessions, allow a bounded two-second drain, then
  abort leftover command tasks and exit.
- The prototype only uses the official `rmcp` SDK for MCP framing, transport,
  lifecycle and negotiation. The line framing above is manager IPC, not MCP.

## Operations

| Operation | Request fields | Successful reply |
|---|---|---|
| `hello` | `protocol_version: 1` | `ok`, supported version, manager name |
| `connect_stdio` | `server_id`, `executable`, `args`, optional string `env` map | connection transport and negotiated protocol |
| `connect_http` | `server_id`, `url` | connection transport and negotiated protocol |
| `status` | — | connected servers and catalog generation |
| `list_tools` | `server_id` | complete SDK tool definitions including JSON input schema and generation |
| `invoke` | `server_id`, exact `tool_name`, JSON object `arguments`, `timeout_ms`, optional `tool_call_id` | source tool identity, ID, generation, content blocks, structured content, metadata, and tool-error classification |
| `cancel` | `target_id` | whether cancellation was requested |
| `disconnect` | `server_id` | session removed and transport cancelled |
| `shutdown` | — | acknowledgement followed by process exit |

The response preserves duplicate names across separate servers by requiring a
`server_id`; it never silently qualifies, rewrites, or merges tool names.
Generation starts at 1 per connection and advances on tool-list changes.
Notifications are `tool_list_changed` with `server_id` and the new generation;
consumers should re-list before dispatching against a changed catalog.

## Errors and uncertain outcomes

Errors have a stable `category`, bounded generic message, and `ok: false`.
Categories distinguish invalid requests, duplicate IDs, capacity, launch,
connection, protocol/transport errors, timeout, cancellation, disconnection,
version mismatch and frame size. A timeout, cancellation or disconnect during
an invocation sets `uncertain: true`: remote side effects may already have
happened. The manager never retries calls. MCP tool-level errors remain normal
completed results with `ok: true`, `is_error: true`, `error_source: "tool"` and
all returned content intact. Protocol errors are separate and do not expose
server exception text or credentials.

## Future production adaptation

The Python caller must remain the authorization owner. A private-worker job
must bind `server_id`, exact tool name, catalog generation, registry
incarnation, chat `tool_call_id`, effective deadline and live permission
decision. Python validates the full input schema and policy before dispatch;
the manager returns the unmodified definition/result and uncertainty class.
The worker command channel should carry bounded acknowledgements, health,
cancellation and shutdown, while catalog-change events and terminal call
results use its event channel. Authentication, crash recovery and generation
reconciliation require an adapter and are not implemented by this prototype.
