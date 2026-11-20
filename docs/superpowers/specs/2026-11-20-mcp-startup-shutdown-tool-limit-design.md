# MCP startup, owned-process shutdown and tool-call preference

## Intent

Saved, enabled MCP servers connect automatically when the add-on loads. Add-on
shutdown releases all application-owned processes. Users choose the maximum
number of tool calls permitted for each response.

## Approach

Use the existing MCP catalog service and private worker; do not introduce another
process owner. Submit startup connections in the background with bounded
concurrency, isolate individual connection failures, and fence queued connections
when shutdown starts. Disabled configurations remain disconnected. HTTP servers
are connected to, never launched or terminated. Existing tool approvals remain
required and are independent of connection state.

The alternative of connecting on the NVDA event thread would block startup.
Keeping MCP connections manual would not meet the requested behavior.

## Shutdown

Fence new requests, runtime starts, MCP connections and UI-host launches before
teardown. Cancel active work, close the MCP catalog, stop initialized owned
runtime executors and the MCP manager in the private worker, then close the
worker and UI host with bounded waits and forced-termination fallback. Do not
initialize an idle runtime merely to stop it. Never kill by executable name:
externally adopted LiteRT-LM/llama.cpp servers and remote MCP servers stay alive.
Retain native kill-on-job-close protection for abnormal worker exit.

Audit UI adapter delivery so queued completion cannot respawn the UI host after
shutdown. Cleanup failures must not prevent remaining owners from closing.

## Tool-call preference

Add a keyboard-accessible, translated numeric setting named “Maximum tool calls
per response” in AI Assistant settings. Proposed default: 100; allowed range:
1–1000. Explain that the limit counts individual calls, including calls grouped
in one model response. Validate before saving and focus invalid input.

Read the saved setting when creating each response's execution tracker so changes
apply to the next response without restarting. Set the iteration ceiling to the
same value so the existing five-round ceiling cannot prematurely defeat it.
Keep existing cancellation, timeout, authorization and result-size controls.
Exhaustion must resolve pending calls into valid tool results and stop requesting
more tool execution; never loop through budget errors until another cap fires.

An unlimited option is excluded because the request asks for a number and the
existing bounded execution architecture should be preserved.

## Validation

Regression tests cover automatic enabled-only startup, independent failures,
shutdown during queued/in-flight startup, owned versus external processes,
late UI deliveries, settings persistence and accessible validation, sequential
and batched call counting, and a configured limit above the old five-round cap.
Run focused tests, full Python suite and Ruff. Validate native consumers if
their implementation changes. Do not restart NVDA or install a package during
the audit without a separate request.

## Current audit evidence

Application initialization constructs McpCatalogService but never connects saved
servers. ToolExecutionBudget defaults to five rounds and 20 calls. Application
termination already invokes stop_host and worker shutdown, and native managed
processes have kill-on-job-close protection; worker shutdown does not explicitly
stop initialized runtime executors. UI host launch currently has no permanent
shutdown fence. These paths need regression coverage before implementation.
