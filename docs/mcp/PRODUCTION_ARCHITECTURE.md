# Production MCP manager architecture

## Ownership

The NVDA Python process owns the application settings, canonical tool registry,
schema validation, permission policy, execution budgets, chat loop and
conversation persistence. It never delegates authorization to an MCP server.

The application starts the existing private CPython worker lazily. The worker
owns one `McpManagerClient` and lazily starts the packaged `mcp_manager.exe`.
The manager uses the official Rust `rmcp` SDK for stdio and Streamable HTTP
sessions, tool discovery, invocation and notifications. It owns stdio child
processes and their Windows Job Object lifetime. The WebView host does not own
MCP processes or issue MCP commands.

## Tool execution

```text
model tool call
  -> Python catalog snapshot and ToolExecutor
  -> argument schema validation and current permission/availability checks
  -> tools/mcp_provider.py
  -> worker MCP job lane and versioned manager IPC
  -> Rust rmcp session
  -> configured MCP server
```

Results return through the same chain. Exact MCP names are carried separately
from model-facing names. Bindings retain server ID, manager session ID, server
incarnation and catalog generation. The registry maintains its own binding
incarnation. The Rust manager rejects stale session/server/catalog identities;
Python bounds and normalizes results before chat history can persist them.

The core schema validator accepts its supported Draft 2020-12 profile and
continues to reject legacy dialect markers. At the MCP catalog boundary, Draft
7 schemas are accepted only when their assertions use the shared supported
profile. The adapter strips the Draft 7 marker after checking for untranslated
Draft 7 or later-draft assertions (`$ref`, tuple `items`, `dependencies`, and
Draft 7 boolean exclusive bounds, among others). Incompatible schemas fail
closed with a path-specific safe diagnostic; shared constraints such as
`required`, `properties`, `enum`, `anyOf`, `items` and `additionalProperties`
remain intact. The installed NVDA MCP Bridge uses Draft 7 schemas and passed
live discovery and a safe read-only operation through this path.

## Catalog and event lifecycle

`McpCatalogService` keeps per-server catalogs and connection state. A catalog
replacement is atomic. Tool-list notifications schedule a bounded refresh for
that server. The worker event queue has a fixed capacity and collapses overflow
to a `resync_required` marker. Notification stream loss also triggers manager
status reconciliation; disconnected servers are made unavailable and removed,
and active servers are refreshed. Rust rejects a list response if the catalog
generation changes during discovery/serialization; Python retries that
specific stale response at most three times.

The catalog event poller runs off the NVDA event thread and is stopped before
worker teardown. Closing settings dialogs only detaches UI observers; it does
not stop sessions or cancel calls. Explicit Disconnect revokes the provider
before sending the manager command. User Stop/cancellation does not claim the
remote side effect was reversed. Calls with uncertain outcomes are never
automatically retried.

## Configuration and authorization

Server records are validated in `config/mcp_servers.py` and persisted via the
settings layer. Stdio executable and arguments come from the configured record.
Streamable HTTP requires HTTPS, except unauthenticated localhost/loopback HTTP.
Bearer tokens are stored using the existing protected settings mechanism,
resolved for connection, and passed only through worker IPC to the Rust HTTP
transport. They are not returned in manager status/replies. Do not place
secrets in URLs, stdio arguments or tool metadata.

External tools are denied by default. Users approve stable tool IDs one at a
time through the keyboard-accessible MCP settings page. The confirmation names
the server and exact tool, and labels its bounded description as untrusted.
Revoking approval
updates the live `ToolExecutor` policy, which signals matching active calls
where their provider supports cancellation. MCP annotations are display data,
not authority. A catalog refresh does not grant approval; changing transport
identity or removing a server clears its approvals.

## Limits and lifecycle

The manager bounds frame size, active commands, control commands, connections,
invocations, per-server invocations, recent request IDs, catalog size, tool
count, startup, requests and shutdown. The Python worker client separately
bounds frames, outstanding requests and notification buffering. Operation
acknowledgements remain distinct from asynchronous manager events. A worker or
manager restart does not replay invocations.

The Windows package build places `mcp_manager.exe` at the add-on root. Rust is
not required on the target machine. The manager's stdio launch and descendant
cleanup use the manager's Windows process containment path; hostile-grandchild
cleanup has a passing Windows fixture test. Full installed-add-on reload,
uninstall and crash-recovery acceptance remains outstanding.

## Verification status

The Python-to-Rust fixture test proves the worker adapter and real Rust manager
can discover and invoke a deterministic fixture. A separate live test connected
to the installed NVDA MCP Bridge and executed the narrowly approved read-only
`list_loaded_addons` operation against the running NVDA process.

On 2026-11-14 the installed assistant was exercised end to end with the
installed NVDA MCP Bridge: added a stdio server for
`%LOCALAPPDATA%\Programs\NVDA MCP Bridge\bin\nvda-mcp-server.exe`, connected it,
discovered 31 tools, approved the read-only `health_snapshot` tool through the
untrusted-description prompt, and asked for it in chat. The model called it
through the worker/Rust manager and answered with NVDA 2026.3.1 and an error
count of 0. The manager process owned a child `nvda-mcp-server.exe`; the test
did not reuse the assistant's separate MCP companion process.

The same live path found and fixed:

- Worker-level manager failures (`success: false` with `error_code`) now use
  the same actionable messages as manager replies instead of collapsing to
  "The external tool connection failed."
- The server list now shows **connected** rather than only **enabled**, and the
  tool summary reports discovered and approved counts.
- Adding or editing a server returns focus to the server list; approving or
  revoking a tool returns focus to the same tool.
- Approving a tool the server declares destructive adds a warning that the tool
  can change state. Annotations remain untrusted and never grant permission.

The discovery follow-up adds a search box and approval/read-only filter to the
tool list, a full description and input-schema preview for the selected tool,
and a single **Approve all read-only** action. The bulk action only considers
non-destructive tools the server claims are read-only, warns that the claim is
untrusted, and leaves every tool individually revocable. The bridge side adds
`find_tools` and `get_tool_schema` so the catalog can be searched before a
schema is loaded; see the bridge's agent-experience document.

Earlier fixes from the same phase: an inaccessible editor crash, focus loss on
tab and server changes, an over-wide editor, and bridge defects in NVDA-menu
state detection and scripted-key dispatch.

The sibling Bridge executable test remains ignored until that sibling checkout
is built. Stdio secret environment references are not exposed by the current
configuration UI; a server that requires an environment-only credential will
fail with the actionable MCP-handshake message rather than exposing the value.
