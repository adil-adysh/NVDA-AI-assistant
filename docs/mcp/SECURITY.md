# MCP manager prototype security and lifecycle

This prototype is isolated under `mcp_client_prototype/` and is not an add-on
runtime dependency. The Python tool executor remains the only production
authorization boundary. No permission UI or production manager adapter is
implemented here.

## Transport trust

- **Local executable:** `connect_stdio` starts only the explicitly configured
  executable and argument list; it does not use a shell. Stdin/stdout are
  reserved for MCP protocol. Stderr is piped and drained without forwarding
  server text or credentials to manager output. Windows children run hidden
  and are wrapped in a Job Object with kill-on-drop containment. This test
  environment verifies direct child shutdown; a dedicated hostile-grandchild
  crash test remains outstanding.
- **HTTP MCP endpoint:** HTTPS is accepted. Plain HTTP is limited to exact
  localhost or loopback IP addresses. URL userinfo is rejected. Arbitrary
  remote plaintext endpoints are rejected. HTTP endpoint credentials are not
  accepted in URLs or copied into diagnostics.
- **Bridge credentials:** The sibling Bridge owns its separate
  `NVDA_BRIDGE_TOKEN` authentication. The integration fixture verifies it is
  passed through the child environment and used in `X-NVDA-Bridge-Token` for
  Bridge API requests; it is not part of manager IPC replies or logs.

## Resource and failure behavior

- Manager JSON-line frames are capped at 1 MiB; request ID history is capped
  at 10,000. Tool timeouts are clamped to 1 ms–5 minutes.
- MCP SDK owns protocol messages, session lifecycle and child transport. The
  manager tracks each invocation cancellation token; timeout, cancellation and
  disconnect are reported as uncertain, with no automatic retry.
- Shutdown fences new connections, cancels pending work, tears down transport
  sessions, waits up to two seconds for command tasks, then aborts remaining
  manager tasks. Side effects already accepted by a server cannot be rolled
  back. The Windows Job Object provides process-tree containment when its job
  handle closes.
- Tool schemas, structured content, text, image/resource content and metadata
  are preserved through SDK serialization, subject to the 1 MiB IPC response
  frame cap. An oversized response is replaced with a bounded error retaining
  the command ID.
- Errors sent to a caller are generic at the protocol boundary; no automatic
  logging of endpoint URLs with secrets or server exception bodies occurs.

## Validation boundary

The real sibling Bridge executable was built from its locked manifest and run
as an MCP stdio child against a local token-checked HTTP fixture. This proves
SDK negotiation, tool listing and invocation against the Bridge implementation.
It does not prove live NVDA endpoint behavior, UI-thread behavior, the Bridge
event long-poll, or containment of a malicious descendant process. The
unrelated Streamable HTTP MCP fixture is independently tested. Production
integration needs Windows worker crash tests, full Bridge event fixture
coverage, authorization wiring, and NVDA-host end-to-end tests.
