# MCP manager security and lifecycle

Status: production integration is present in the current worktree; live NVDA
accessibility and installed add-on reload/uninstall checks remain open.

## Trust boundaries and authorization

- The manager is a private child of the application-owned CPython worker. It
  reads commands only from worker stdin and writes replies/events to worker
  stdout; it opens no listener. The `hello` version negotiation is protocol
  compatibility, not authentication. Process ownership and the private pipe
  are the parent trust boundary.
- WebView events, documents, tool outputs and server metadata cannot issue
  manager commands. Python resolves the catalog snapshot, validates schemas,
  checks live availability and host policy, applies execution budgets, and
  normalizes/bounds results before persistence.
- External tools are denied by default. User approvals are per stable tool ID
  and stored separately from server definitions. MCP annotations never grant
  permission. Revoking a tool updates the executor's live policy and requests
  cancellation of newly unauthorized active work.
- Server IDs, session incarnations, catalog generations, registry binding
  incarnations and tool-call IDs are checked independently. Stale manager,
  server or catalog identities fail closed; no uncertain invocation is retried.

## Transport trust and credentials

- **Stdio:** the worker launches only the explicitly configured executable and
  argument list through `CreateProcess`/Rust `Command`; there is no shell.
  Stdin/stdout carry MCP frames. Stderr is drained without forwarding server
  text. Windows child processes are hidden and wrapped in a Job Object with
  kill-on-drop. A hostile-grandchild test verifies process-tree termination.
  The settings UI currently does not expose environment-variable secret
  references; users must not put credentials in executable arguments.
- **Streamable HTTP:** HTTPS is allowed. Plain HTTP is restricted to localhost
  and loopback IP addresses. URL userinfo, query parameters and fragments are
  rejected. Optional bearer tokens are stored as a top-level DPAPI-protected
  config value, while server records contain only a credential reference. The
  token is sent in the HTTP authorization header and is not included in logs or
  manager replies. Tokens are bounded, ASCII-only and reject line breaks.
- HTTP redirects use the official `rmcp`/reqwest client policy; cross-origin
  redirects are rejected. The manager does not configure an ambient proxy or
  expose a network listener. Endpoint resolution and TLS still rely on the
  platform/network stack; HTTPS does not establish that a server is trustworthy.
- **Bridge credentials:** NVDA MCP Bridge's separate `NVDA_BRIDGE_TOKEN` is
  configured in its own process environment. Its Bridge API authentication is
  distinct from the manager's Streamable HTTP bearer token.

## Resource, cancellation and failure behavior

- Manager JSON-line frames are capped at 1 MiB. Active commands, connections,
  invocations, per-server invocations, pending calls, catalogs, notification
  broadcast and request-ID history are bounded. Saturated operations fail with
  a capacity result before dispatch. Control operations have a separate
  reserved capacity; process-level command saturation tests confirm `status`
  and `shutdown` remain responsive. The optional ordinary command limit is
  clamped to 1–128 (`32` by default).
- Rust `tools/list` pagination is consumed incrementally with cumulative
  catalog count and serialized-byte checks, repeated-cursor detection and a
  64-page maximum; it does not use RMCP's unbounded `list_all_tools()` helper.
- Initialization and tool calls have bounded deadlines. Concurrent connects
  reserve server IDs atomically. A failed catalog fetch after connect triggers
  bounded disconnect cleanup; a failed cleanup does not make tools available.
- Python cancellation is propagated as a manager `cancel` command. `rmcp`
  3.9.0's `call_tool` wraps requests in an abandoned-request guard; dropping
  the future sends a best-effort `notifications/cancelled`. This is a request
  to the server, not proof that it stopped. Timeouts, cancellation, disconnect
  and manager failure can leave remote side effects unknown; results say so and
  the application never retries automatically.
- Explicit manager shutdown and stdin EOF fence new work, cancel sessions and
  pending invocations, drain for a bounded interval, then abort leftover tasks.
  The worker owns the manager lifecycle and closes it during worker shutdown.
  Worker recovery does not replay invocation jobs.
- Tool schemas, structured content, text, image/resource content and metadata
  pass through SDK serialization and Python result bounding. Oversized manager
  frames fail as protocol errors; Python separately enforces its persisted
  result envelope limit.

## Evidence and limitations

- Windows Job Object hostile-grandchild test passed on the current Windows
  host. A real safe read-only `list_loaded_addons` call succeeded against the
  live NVDA Bridge through the manager, worker adapter, catalog and Python
  executor, using one narrowly scoped test approval. The installed settings UI,
  keyboard approval journey, screen-reader announcements and add-on reload have
  not been run.
- The latest packaged manager is 4,476,416 bytes and the rebuilt
  `.nvda-addon` is 24,338,831 bytes (1,038 entries) with no tests, test modules
  or bytecode entries. Packaged worker smoke tests passed 5/5; the packaged
  manager passed both Python/Rust fixture integration tests.
- `rmcp` transport cancellation is best effort. A server may ignore it or
  finish a side effect before cancellation arrives. The application cannot
  roll back a remote operation.
- Cancellation after tool dispatch is classified as uncertain with
  `termination_confirmed=false`; cancellation before dispatch is confirmed and
  non-uncertain. The Python/Rust fixture regression records a side effect
  before cancellation to verify this distinction.
- Worker event-queue overflow emits `resync_required`; the Python catalog
  poller consumes it and reconciles manager status, retiring absent servers and
  refreshing active catalogs. Notification stream loss uses the same recovery
  path. Stale list generations are retried at most three times. Live Bridge
  schemas declare Draft 7; the catalog adapter accepts only the common
  supported assertion subset and rejects incompatible legacy semantics.
- Catalog refreshes coalesce notifications arriving mid-refresh into one
  follow-up read. Disconnect, reconnect and manager retirement advance a
  per-server revision and fence stale refresh completion before registry
  publication or availability changes. A disconnected server stays blocked
  until an explicit successful reconnect.
- Catalog refreshes coalesce notifications arriving mid-refresh into one
  follow-up read. Disconnect, reconnect and manager retirement advance a
  per-server revision and fence stale refresh completion before registry
  publication or availability changes. A disconnected server stays blocked
  until an explicit successful reconnect.
- Rust `tools/list` pagination is consumed incrementally with cumulative
  catalog count and serialized-byte checks, repeated-cursor detection and a
  64-page maximum; it does not use RMCP's unbounded `list_all_tools()` helper.
- The sibling Bridge stdio fixture and generic Streamable HTTP fixture are
  simulated protocol checks. They do not establish live NVDA endpoint behavior.
