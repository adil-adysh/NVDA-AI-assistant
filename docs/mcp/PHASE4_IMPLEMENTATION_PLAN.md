# Phase 4: Production MCP Manager Hardening and Integration

**Goal:** Integrate a bounded Rust `rmcp` manager with the existing Python tool registry and worker so configured MCP tools execute through the Assistant's existing validation, authorization, cancellation, result and persistence path.

**Architecture:** Python remains authoritative for catalog registration, schemas, permissions, and tool execution. The private, lazily launched worker owns one MCP manager process and submits bounded serialized jobs; the manager owns MCP sessions and child processes. Discovery, catalog generations, server incarnations, and Python registry binding incarnations are reconciled before dispatch. UI configuration follows only after this execution boundary works end to end.

**Tech stack:** Python 3.13, existing worker/job protocol and settings store, Rust/Tokio, official `rmcp` 3.9.0 client, Windows named pipes and Job Objects, Svelte/NVDA settings surfaces.

**Spec:** User-provided Phase 4 assignment (P00–P10), with IPC baseline in `docs/mcp/IPC_CONTRACT.md` and Phase 3 evidence in `docs/mcp/SECURITY.md`.

## Decisions

- Keep MCP lifecycle out of `nvda_ui_host.exe`; use the application-owned private worker and an independently supervised manager child.
- Reuse `ToolProvider`, `ToolRegistry`, `ToolExecutor`, worker job lanes, JSON schema validation and result normalization; add no second authorization or catalog system.
- Treat external schemas as input to existing validation. Keep `server_id`, session incarnation, catalog generation, exact source tool name, internal stable `tool_id`, registry binding incarnation, request ID and tool-call ID distinct.
- Model cancellation as a request and preserve `uncertain` outcomes. Never automatically retry calls after timeout, manager death or ambiguous disconnect.
- Implement deterministic configuration and approval UI only after Rust lifecycle, worker adapter and Python dispatch are verified. External tools default to denied; annotations cannot approve.
- Remote changes require explicit authorization. The user explicitly requested merging to `main` and pushing in this thread; the worktree is already on `main`.

## Dependencies and order

1. P00 baseline and audit precede manager changes.
2. P01 lifecycle reservation/deadlines and P02 capacity bounds establish safe manager primitives.
3. P03 IPC handshake/ownership and P04 cancellation/shutdown depend on the lifecycle and capacity model.
4. P05 worker-backed Python provider depends on stable bounded IPC operations.
5. P06 discovery/reconnect depends on P05 identity and generation plumbing.
6. P07 accessible server/approval UI depends on P06; server management can be staged independently from per-tool approval.
7. P08 package and process-tree guarantees depend on integrated ownership.
8. P09 acceptance matrix and P10 independent audit close release gates.

## Risks and constraints

- Existing worker APIs and runtime job lanes are synchronous/serialized by domain; an MCP lane must not block command listeners, NVDA's event thread, or unrelated servers.
- Existing restart recovery can create a new worker generation. MCP sessions must be fenced by manager/session incarnation and must not replay tool calls.
- `rmcp` cancellation support varies by negotiated protocol revision and server behavior. Report the local request, SDK transmission where observable, and unknown remote outcome separately.
- Windows Job Object behavior must be proved for grandchildren and manager crash, not inferred from direct-child shutdown.
- Settings and approval storage must preserve deny-by-default behavior, avoid leaking HTTP credentials, and not treat server descriptions/annotations as trusted.
- Real NVDA is not assumed available. Simulated HTTP fixtures cannot satisfy live-NVDA acceptance items.
- Keep all tests under top-level `tests/`; preserve unrelated pre-existing host JS modifications and `.superpowers/`.

## Acceptance gates

- All connection attempts have bounded startup and cleanup; duplicate IDs cannot race; unrelated servers progress independently.
- Manager concurrency, queues, catalogs, reply sizes, pending requests and notification buffers have explicit caps; control-plane work remains available under load.
- IPC requires successful version negotiation and a private worker-owned process boundary; no untrusted UI or tool payload can issue manager operations.
- Cancellation and shutdown preserve uncertain side-effect outcomes, correlate terminal results and clean up manager-owned children.
- Every MCP operation traverses Python schema validation, live authorization, registry incarnation checks and `ToolExecutor`; results pass existing bounded normalization/persistence.
- Multi-server catalog refresh/reconnect cannot redirect a retained snapshot or restore revoked permission.
- Keyboard and screen-reader users can configure, inspect, approve, deny and revoke external tools without focus theft.
- Packaged Windows add-on owns and contains manager/descendants, starts without Rust installed, and removes them on shutdown/reload.
- P09 deterministic tests and P10 required checks pass. Real NVDA gates are reported as executed or explicitly unavailable.

## Task tracking and evidence

### P00 — Baseline, audit and plan

- [x] Read the repository guide, architecture/tool hardening records and Phase 3 contract/security documents.
- [x] Inspect the manager protocol/lifecycle, registry/executor, worker job lanes, MCP adapter/catalog, settings dialog, chat loop and package build hooks. P07 configuration/approval UI and notification-to-catalog reconciliation remain incomplete.
- [x] Fresh current-tree checks: `uv run ruff check .` passed; `uv run pytest tests/tools -q` passed 121; `uv run pytest` passed 1,283, 3 skipped, 40 deselected. This run includes the uncommitted production MCP work and predates the event-overflow regression added below.
- [x] Create this plan with decisions, dependencies, risks and acceptance criteria.

### P01–P04 — Rust manager hardening

- [x] Lifecycle state/reservation, startup deadlines, cancellation and cleanup for stdio and HTTP (Rust fixture tests cover hanging/failed startup, duplicate reservation, shutdown cancellation, and unrelated server progress).
- [x] Bounded command/connection/invocation/catalog/reply/cancellation/event capacities with control-plane priority (command semaphore capacity/reserved control slot have direct unit coverage; piped command-saturation plus status/shutdown control-plane behavior have a process-level regression; shutdown under invocation saturation has transport-level coverage).
- [x] Successful IPC version handshake before operations; the private worker owns the manager process and does not expose the endpoint to UI events.
- [x] Explicit shutdown and stdin EOF fence launches, cancel connections and invocations, and drain/abort command tasks within a bounded deadline. Process-level EOF-during-startup and Windows child-exit regression passed.
- [ ] Complete SDK cancellation/deadline audit and remaining recovery matrix; protocol cancellation remains best-effort and uncertain results are not retried. Command saturation and reserved control-plane responsiveness are verified through the JSON-lines manager process; parent EOF during an active invocation exits the manager and cleans up its server child; timeout after a recorded side effect returns `uncertain: true`. A remote cancellation acknowledgement is not provided by the audited SDK path.
- [ ] Deterministic races, timeout, cancellation, saturation, recovery and child lifecycle tests (current suite covers major startup, cancellation, server saturation and EOF paths; sibling Bridge interoperability remains ignored without its built executable).

### P05–P06 — Python adapter and catalog lifecycle

- [x] Add a worker-owned MCP manager adapter through existing worker lanes and operation schemas.
- [x] Implement `ToolProvider` adapter that returns existing result DTOs and propagates context/cancellation/deadlines.
- [x] Register/replace per-server catalogs atomically; preserve server/session/catalog generations and registry incarnations.
- [x] Consume manager events on a bounded Python poller; list changes schedule per-server catalog refresh, queue overflow and notification-stream loss trigger authoritative status resynchronization, and disconnected servers are retired from the registry. A stale catalog generation during Rust list serialization returns `stale_catalog`; Python retries it at most three times. Notifications during refresh coalesce into one follow-up, and disconnect/reconnect revisions fence stale completion. Regressions include the notification-coalescing and disconnect-fencing tests in `tests/tools/test_mcp_catalog.py`.
- [x] Demonstrate Python ToolExecutor → provider/catalog → worker → real Rust manager → fixture server with bounded results, authorization denial/approval, malformed-argument rejection, and correlated multi-call chat persistence (`tests/integration/test_mcp_cross_language.py`, 3 passed on 2026-11-13).
- [x] Exercise cancellation after the RMCP fixture records a side effect. The end-to-end regression verifies `cancelled=true`, `uncertain=true`, and `termination_confirmed=false`; a separate executor regression verifies cancellation before dispatch is confirmed and not uncertain. This caught and fixed an outcome-classification defect in `ToolCancelledError`.

### P07 — Accessible configuration and approval

- [x] Persist server configurations and non-secret credential references safely; add/edit/enable/disable/remove stdio and Streamable HTTP entries. HTTP bearer credentials are stored through the protected settings store and resolved only for connection.
- [x] Inspect connection status and discovered tools; expose safe status and a keyboard-accessible Refresh tools action.
- [x] Add default-deny, per-tool approval/revocation integrated with the existing permission policy. The confirmation identifies server/tool and labels the bounded description untrusted. Transport identity edits and removal clear associated approvals.
- [ ] Verify keyboard-only use, names/descriptions, announcements, focus order, dismissal and NVDA speech behavior.

### P08–P09 — Windows packaging and acceptance

- [x] Integrate manager process ownership into lazy worker startup/shutdown and recovery; fence manager/session generations.
- [x] Verify hostile-grandchild cleanup under the Windows Job Object for both cancelled startup and abrupt manager termination (`cancelling_startup_kills_hostile_grandchild_in_manager_job_object` and `abrupt_manager_exit_cleans_up_connected_server_process_tree` passed); installed add-on update and NVDA restart were later verified, while uninstall acceptance remains open.
- [x] Package manager deterministically and inspect the archive: latest manager executable 4,473,344 bytes; package 24,339,321 bytes; 1,038 entries; zero test/fixture/bytecode entries. Latest packaged worker and cross-language smoke tests passed 6/6. The installed AIAssistant 0.14.0 directory contains `ui/mcp_settings.py` and the 4,473,344-byte manager; NVDA restarted and reported the add-on running. Uninstall acceptance remains open.
- [ ] Complete Rust-only and Python/Rust acceptance matrices. Latest Rust transport suite passed 24 with 1 ignored; Python/Rust fixture and deterministic chat/persistence acceptance passed 4. Startup/EOF (including active invocation)/cancellation/timeout/server/command saturation paths are covered, including process-tree cleanup after manager termination. Chat cancellation, tool-level error/content preservation, correlated multi-call persistence and conversation-switch fencing have end-to-end coverage; worker-level replacement of a failed manager is tested, while integrated reconnect/re-discovery and uninstall acceptance remain open.
- [x] Run a real safe read-only MCP Bridge operation against the running NVDA process through the packaged manager, worker command adapter, Python catalog and ToolExecutor: discovered 31 tools, approved `list_loaded_addons` narrowly, and got a correlated successful result (`live-nvda-read-1`). This direct acceptance path did not exercise the installed assistant UI or keyboard approval flow.
- [ ] Verify keyboard approval/revocation and screen-reader responsiveness in the installed assistant settings UI. NVDA restarted after the add-on update and the add-on is running, but the bridge keyboard gesture `nvda+n` moved desktop focus instead of opening NVDA's menu; Computer Use initialization still fails because its kernel assets path is unavailable. Recent NVDA log searches found no warnings or errors attributed to AIAssistant or nvdaMcpBridge.

### P10 — Final audit

- [ ] Review concurrency, lock ordering, resource limits, authorization, prompt injection, identity/generation, retry, secrets, UI thread affinity, accessibility and packaging.
- [ ] Run all commands from `AGENTS.md` and this phase spec after the latest changes; inspect actual package and Windows process cleanup results.
- [ ] Update IPC/security/production architecture and tool-system migration docs with evidence and deferred blockers.
- [ ] Report each P00–P10 status, files, tests, commit IDs, baseline/final counts, package impact, actual Windows/NVDA results and release readiness.

### Current follow-up evidence (2026-11-13)

- Fresh validation on `main` at `ad4d641391eec9efa1a7740e287ce05ef1a5a644`: `uv sync --locked`, Ruff, and `uv run pytest tests/tools -q` passed (133); the full Python suite passed 1,316, skipped 3, and deselected 40. Host `cargo check`, runtime supervisor tests (24), MCP formatting, Clippy with warnings denied, and the serial fixture-enabled Rust suite (24 transport passed, 1 sibling Bridge test ignored, plus the command-admission unit test) passed. Web UI build and all 49 tests passed; `uv run scons --dry-run` and `uv run scons` passed. The rebuilt archive is 24,339,321 bytes with 1,038 entries, includes `mcp_manager.exe`, and contains no tests, fixtures, Python bytecode, or pytest files. `git diff --check` passed.
- Live NVDA follow-up: the user authorized completing the open installer prompt. The AIAssistant update proceeded to installation, then a Restart NVDA prompt; accepting it made NVDA temporarily unreachable, after which the bridge returned. `list_loaded_addons` reports AIAssistant 0.14.0 running; installed `globalPlugins/AI-assistant/ui/mcp_settings.py` and `mcp_manager.exe` are present, with the manager matching the packaged 4,473,344-byte binary. Recent AIAssistant and nvdaMcpBridge warning/error log searches returned no matches. The NVDA settings UI keyboard/screen-reader workflow and add-on uninstall remain unverified.

- Latest fixes: `McpCatalogService` now coalesces tool-list notifications during an in-flight refresh and fences catalog publication/availability on disconnect, reconnect, retirement and shutdown revisions. Rust no longer uses RMCP `list_all_tools()`; `tools/list` pages are accumulated with cumulative count/serialized-byte checks, repeated-cursor detection and a 64-page cap. Regressions: `test_notification_during_refresh_coalesces_a_follow_up_catalog_read`, `test_disconnect_fences_inflight_notification_refresh`, and `bounded_catalog_stops_after_crossing_tool_count_limit`.
- Final checks after the end-to-end cancellation classification fix: `uv sync --locked`; Ruff clean; full pytest with packaged smoke and MCP fixture gates enabled: 1,318 passed, 2 skipped, 40 deselected; `tests/tools` 133 passed; Rust MCP formatting, Clippy `-D warnings`, and transport tests 19 passed/1 ignored; host `cargo check`; runtime supervisor 24 passed; Web UI 49 passed and build clean; SCons dry run/build; packaged worker smoke 2 passed; Python/Rust cross-language and chat/persistence acceptance 3 passed.
- At that earlier checkpoint, the archive was 24,338,831 bytes with 1,038 entries and a 4,476,416-byte Rust manager; no test/fixture/bytecode entries. Windows hostile-grandchild Job Object cleanup remained verified, and a live installed NVDA Bridge read-only call had succeeded. Installation and keyboard/screen-reader validation were still pending then; the later live installation/restart evidence is recorded below.

- Phase 4 began at `4a6e7ca`; implementation changes are being committed on the already-current `main` branch. The unrelated modified host JavaScript files and `.superpowers/` directory are preserved.
- Added a deterministic red/green regression for local notification-queue overflow. Before the fix the event was dropped; after the fix `uv run pytest tests/worker/test_mcp_manager_client.py -q` passed 6 tests and targeted Ruff passed.
- Added the Python notification consumer and authoritative resynchronization. On shutdown, the application fences the catalog poller before shutting down the worker; poll commands observe the stop signal.
- Follow-up validation: Python catalog/worker-client tests now include stale-generation retries, missed-notification reconciliation, Draft 7 schema mapping and incompatible-keyword rejection. `ruff check .` passed; Rust fmt check and Clippy with `-D warnings` passed; Rust transport tests passed 14 with 1 sibling-build Bridge test ignored (serial execution); release manager/fixture build passed; Python Executor → worker → Rust manager → fixture acceptance passed 2 (direct tool call and chat/persistence).
- A first parallel Rust test run had one timeout in the independent-server progress test; the exact test passed on isolated rerun and the serial full transport suite passed. Treat parallel contention as a test stability concern to review.
- The live installed Bridge was reached after removing an insecure inherited `NVDA_BRIDGE_TOKEN` placeholder from the test process environment; the child then resolved the user's generated token file itself. The actual NVDA Bridge advertised Draft 7 schemas, which initially failed the strict core schema dialect check. The MCP catalog now strips the Draft 7 marker only for the common supported assertion profile and rejects untranslated Draft 7 assertions; regression tests cover both.
- Remaining high-priority work is full cancellation/saturation/chat acceptance, live keyboard/NVDA accessibility verification, complete package/restart/crash-recovery matrix, remaining required validation, and independent audit. Stdio secret environment reference support is also incomplete; the settings UI does not expose secret-bearing env values.
- Final Python validation after Draft 7 mapping, approval confirmation and shutdown fencing: `uv sync --locked` passed; `uv run ruff check .` passed; `uv run pytest` passed 1,306, skipped 3, deselected 40; `uv run pytest tests/tools -q` passed 131. `uv run scons --dry-run` and `uv run scons` passed. Packaged worker smoke passed 5; packaged-manager Rust/Python fixture plus chat/persistence acceptance passed 2. Archive inspection found 1,038 entries, the manager executable, and zero tests/test modules/bytecode.
- Live NVDA Bridge acceptance: 31 tools discovered; narrowly approved `list_loaded_addons` executed successfully with call ID preserved and the Assistant add-on present. The three previously running Bridge companion processes remained the same; the temporary manager session was closed. Real settings UI keyboard/speech validation remains blocked by the desktop automation kernel failure and is still a release gate.
- Independent Rust listener audit found and reproduced a pending-request leak: `run_stdio` reserved invocation cancellation records before the handshake check, while the handshake rejection returned before deleting them. Eight rejected pre-handshake invokes exhausted the bounded pending map and rejected a later valid invoke. A regression failed with `pending invocation limit reached`; command-task terminal cleanup fixes it. The process-level regression now passes, and the full serial manager suite currently reports 16 passed with one sibling Bridge test ignored. Parent EOF during a hanging startup also exits within the test deadline and confirms the Windows-owned child process exits. Rust formatting and Clippy are being rerun after these additions.
- Follow-up saturation regression: with `max_active_invocations=2` occupied by two side-effecting fixture calls, `Shutdown` returns within 300 ms and both calls terminate as uncertain `cancelled`/`disconnected` outcomes. `cargo fmt --check`, Clippy `-D warnings`, and the serial transport suite pass (20 passed, 1 ignored). The regression closes the control-plane-under-invocation-saturation gap; it does not yet saturate the independent JSON-lines command semaphore itself.
- Command admission uses a shared helper in `run_stdio`; a unit test verifies the bound, reserved control capacity and release on completion. The process-level test below exercises the same behavior through piped JSON-lines.
- Process-level command-saturation regression: with `NVDA_MCP_MAX_ACTIVE_COMMANDS=1`, a hanging stdio initialization occupies the ordinary slot, a second connection receives `capacity`, while `status` still reports the connecting server and `shutdown` completes within 500 ms and exits the manager. The override is parsed as a limit and still passes through the manager's existing hard clamp. Serial transport suite now reports 21 passed and one ignored sibling-Bridge test; the command-admission primitive unit test also passes.
- Rebuilt after the command admission change: `uv run scons` passed. Current package is 24,339,319 bytes; included manager is 4,473,344 bytes; archive contains 1,038 entries and zero test/fixture/bytecode/pytest entries. Packaged worker smoke plus Python/Rust/chat acceptance passed 6/6.
- Added a Python/Rust/chat regression that switches conversations after the MCP fixture records the slow tool side effect. The call completes, the stale model answer is returned to the originating request, and the old conversation transcript is not committed; the new conversation remains active and empty. `tests/integration/test_mcp_cross_language.py` now passes 4 tests.
- Fresh final Python validation after the added chat-switch and Rust manager changes: `uv run ruff check .` passed; packaged-gated `uv run pytest` passed 1,319, skipped 2, deselected 40 (1,321 selected). Rust formatting and Clippy with warnings denied passed; serial Rust tests passed 21, with one sibling Bridge interoperability test ignored because its separate executable is not built.
- Abrupt-manager-exit cleanup is now verified on Windows with the fixture feature enabled: after successful connection, the manager is force-terminated and both the connected stdio server and its grandchild exit. The `cargo test --all-targets --features fixture-server -- --test-threads=1` run passes 22 transport tests plus the command-admission unit test, with only sibling Bridge interoperability ignored; Clippy `-D warnings` and Rust formatting pass.
- Parent stdin EOF during a fixture `slow` invocation is now verified separately: after the tool writes its process ID marker, closing stdin lets the manager exit within three seconds and the Windows-owned server process exits as well. The call remains an unknown remote side-effect outcome; the test checks cleanup and bounded exit, not remote cancellation acknowledgement.
- Timeout-after-side-effect test: one `slow` invocation records its marker before a 50 ms deadline; the manager returns category `timeout` with `uncertain: true`, preserving the no-retry contract. The focused regression passed; the complete fixture-enabled Rust suite will be rerun after this addition.
- Worker recovery regression: `WorkerServer.get_mcp_manager()` closes a failed manager client and creates a new lazy client with an empty pending-request map; it does not replay the failed invocation. `uv run pytest tests/worker/test_mcp_manager_client.py -q` passes 13 tests. Integrated reconnect/re-discovery after an actual manager crash remains open.
- Chat-level MCP tool failure is now covered in the correlated multi-call acceptance: the real Rust fixture's `tool_error` result is persisted with `execution_error`, `error_source=tool`, and original text in the bounded structured content, while the model-visible text remains the generic safe error. The focused cross-language chat test passes.
- Fresh Python validation after the recovery and tool-error acceptance additions: packaged-gated `uv run pytest` passed 1,320, skipped 2, deselected 40 (1,322 selected); `uv run ruff check .` passed.
- The installed NVDA add-on currently lacks `mcp_settings.py` and `mcp_manager.exe`; live keyboard/speech validation against the new UI is therefore not yet possible without installing the newly built package. The current source contains the new settings panel, but static UI tests are not a substitute for installed NVDA interaction.

## End-user acceptance (2026-11-14)

Installed-AI Assistant and NVDA MCP Bridge were exercised through the live NVDA
process and the bridge MCP tools. The acceptance itself found and fixed these
defects.

- MCP server editor: `wx.Dialog.CreateSeparatedButtonSizer()` created buttons
  owned by the dialog, then added them to the panel's sizer. wx raised an
  assertion before the editor appeared, so Add/Edit never worked. The button
  sizer now belongs to the dialog's outer sizer. Regression:
  `test_mcp_server_editor_validates_before_closing_and_keeps_safe_defaults`.
- MCP editor and settings focus: both dialogs opened with focus on OK because
  wx applies the default button after construction. `EVT_SHOW` now moves focus
  to the first field/list control after the dialog is visible.
- MCP tab: the `&` in "MCP Servers & Tools" was interpreted as an accelerator,
  producing an inaccessible name. The tab is now "MCP Servers and Tools".
- Tab switching dropped focus because `_on_page_changed` focused a non-focusable
  panel. It now focuses the first usable control on the page, and the notebook
  has a fallback. Regressions: `test_tab_switching_focuses_the_first_usable_control`,
  `test_removing_a_server_restores_focus_to_the_list`.
- The server editor was 1,354 px wide because the unwrapped security guidance
  text set the best size; the arguments field was one line tall. The guidance is
  wrapped, the arguments field has a usable minimum height, the dialog is
  centred on its parent, and OK/Cancel remain reachable.
- Invalid input and duplicate server IDs closed the editor after `ShowModal`,
  discarding every field. Validation now runs on the OK button, shows the error,
  and leaves the form intact. The duplicate check moved into the editor.
- Approve-tool and Remove-server confirmations defaulted to Yes. Both now use
  `wx.NO_DEFAULT`; focus lands on No and the destructive action requires an
  explicit move. Verified live: the Remove prompt opened with "No" focused.
- Connection failures spoke only "MCP operation failed". Manager error categories
  now map to actionable safe messages (launch path, MCP handshake/environment,
  URL/token, protocol version, capacity, oversized result), and the status field
  and speech use that message. Regression:
  `test_manager_failure_categories_produce_actionable_safe_messages`.
- Removing a server left focus nowhere. Focus returns to the configured-server
  list after the list is rebuilt.

Live end-user path, using DeepSeek through the OpenAI-compatible provider with
the user's key and `https://api.deepseek.com` plus model `deepseek-flash`:

1. Opened `NVDA menu -> Tools -> AI Assistant -> Settings... -> MCP Servers and
   Tools`; focus landed on the server list.
2. Added a stdio server for `mock_mcp.exe`, connected it, discovered four tools,
   and approved `echo` through the untrusted-description confirmation.
3. Sent "Call the echo tool with the value 42 and tell me what it returns." The
   model selected the approved MCP tool, the worker/Rust manager executed it, and
   the chat rendered "The echo tool returned: stdio:echo" and a follow-up
   explanation. The transcript exposes headings, paragraphs and tool text through
   the WebView accessibility tree.
4. Re-opened Add, reused the `mock` ID, confirmed OK, and verified the error kept
   the editor and all values; cancelled the editor.
5. Removed the unused `nvda-mcp` entry, confirmed the safe No default, moved to
   Yes, and verified the list rebuilt with focus restored.

Bridge defects fixed during the same run:

- A stale `nvdaMenuIaIdentity` (`True`) blocked every input action until NVDA
  restarted. Menu state now prefers the GUI thread's `GUITHREADINFO` menu flags,
  then the native popup window, and falls back to the identity only when no
  foreground window exists.
- `press` was forbidden in menu/modal states, so the bridge could open the NVDA
  menu but never navigate it. `press` is now allowed in both states.
- `KeyboardInputGesture.send()` re-injected NVDA-bound commands and leaked the
  main key to the focused app (for example "n" moved browser focus instead of
  opening the menu). Scripted gestures now run through
  `inputCore.manager.executeGesture` on NVDA's queue; only unscripted keys are
  injected.

Evidence: `uv run ruff check .` passed; `uv run pytest` passed 1,321, skipped 3,
deselected 40; Rust host `cargo check` passed; runtime supervisor 24 passed;
`uv run scons --dry-run` and `uv run scons` passed. The package is 24,340,582
bytes with 1,038 entries, `mcp_manager.exe` (4,473,344 bytes), the new
`ui/mcp_settings.py`, and no tests or bytecode. Bridge regressions: 11
`test_http_bridge`, 30 `test_action_tools`, 15 `test_keyboard_dispatch` (all
passing; the full bridge discovery run has one unrelated missing-pytest import).

## NVDA MCP Bridge acceptance (2026-11-14)

Added the installed Bridge companion as a stdio server through the live
**MCP Servers and Tools** page:

- Server ID `nvda-mcp`; executable
  `C:\Users\adilh\AppData\Local\Programs\NVDA MCP Bridge\bin\nvda-mcp-server.exe`.
- **Connect** discovered 31 tools and the server list changed from *enabled* to
  *connected*.
- Approved the read-only `health_snapshot` tool through the untrusted-description
  confirmation.
- Asked in chat: "Use the health_snapshot tool from the NVDA MCP Bridge and tell
  me the NVDA version and whether any errors are reported." The model called the
  tool through the worker/Rust manager; the answer reported NVDA 2026.3.1 and an
  error count of zero.
- The manager's process tree contained a child `nvda-mcp-server.exe`, separate
  from the Bridge companion already used by the DSH MCP client.

The live path also found and fixed worker-level error handling: manager startup
or transport failures (`success: false` with `error_code`) were collapsing to a
generic connection message. They now use the same actionable category guidance
as manager replies. The settings page now labels connected servers, reports the
discovered/approved tool counts, returns focus to the server list after
add/edit, returns focus to the selected tool after approve/revoke, and adds a
warning when a server declares a tool destructive. Annotations remain untrusted
and cannot authorize a tool.

Validation after these changes: `uv run ruff check .` passed; `uv run pytest`
passed 1,327, skipped 3, deselected 40, with 60 subtests; `uv run scons`
produced `AIAssistant-0.14.0.nvda-addon` (24,343,076 bytes) containing the new
`tools/mcp_errors.py`. The package was installed over 0.14.0, NVDA restarted,
the Bridge server reconnected, the list showed **connected**, all 31 tools and
the persisted approval were present, and a second chat turn again returned NVDA
2026.3.1 with 0 errors while the Bridge log recorded a successful
`health_snapshot` action. The assistant's manager process owned a separate
`nvda-mcp-server.exe` child.

## Tool-discovery follow-up

The settings page now supports search, approval/read-only filters, a full
description and input-schema preview, and one warning-led bulk approval for
non-destructive tools the server claims are read-only. Each approval remains
individually revocable, and the bulk prompt states that the server's claim is
untrusted.

The bridge companion adds `find_tools` (compact summaries with required
parameters) and `get_tool_schema` (one input schema on demand), so an agent can
search before paying for a schema. The default Bridge catalog is now 33 tools
(34 with developer mode) because those two tools are themselves discoverable.

Validation: Assistant `uv run pytest` passed 1,335, skipped 3, deselected 40,
with 60 subtests; Ruff clean; final package `AIAssistant-0.14.0.nvda-addon`
is 24,346,457 bytes, SHA-256 `589C6CCB…`. Bridge `pytest` passed 601 with 19
subtests; Rust `cargo test` passed 40; final package
`nvdaMcpBridge-0.10.0.nvda-addon` is 4,616,151 bytes, SHA-256 `3832EF7E…`.

## Baseline

The hardening baseline at `70eaaba60d246bce1728550b70fcc1fb1934d213` is recorded above. Phase 4 began from current HEAD `4a6e7ca`. The worktree also contains unrelated host JavaScript edits and untracked `.superpowers/`; these are user work and must be preserved.

## Plan review

The spec names one compatible production architecture and explicitly rejects a second policy system, UI-host ownership, and direct WebView execution. Therefore no competing implementation is being introduced. The task order preserves the stated security dependency: manager primitives first, then worker/Python execution, then catalog/UI/package integration. The supplied Phase 4 specification authorizes implementation, so execution proceeds in this order without a separate scope-selection pause.
