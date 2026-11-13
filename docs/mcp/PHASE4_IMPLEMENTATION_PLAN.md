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
- [x] Bounded command/connection/invocation/catalog/reply/cancellation/event capacities with control-plane priority (command semaphore capacity/reserved control slot have direct unit coverage; shutdown under invocation saturation has transport-level coverage; piped command-saturation coverage remains open).
- [x] Successful IPC version handshake before operations; the private worker owns the manager process and does not expose the endpoint to UI events.
- [x] Explicit shutdown and stdin EOF fence launches, cancel connections and invocations, and drain/abort command tasks within a bounded deadline. Process-level EOF-during-startup and Windows child-exit regression passed.
- [ ] Complete SDK cancellation/deadline audit and full command-saturation/recovery matrix; protocol cancellation remains best-effort and uncertain results are not retried. Tests now verify bounded command admission with reserved control capacity and prove shutdown stays responsive when the global invocation limit is occupied; process-level JSON-lines command saturation remains untested.
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
- [x] Verify hostile-grandchild cleanup under the Windows Job Object (`cancelling_startup_kills_hostile_grandchild_in_manager_job_object` passed); add-on reload and crash-recovery acceptance remains open.
- [x] Package manager deterministically and inspect the archive: latest manager executable 4,476,416 bytes; package 24,338,831 bytes; 1,038 entries; zero test/fixture/bytecode entries. Packaged worker smoke tests passed 2/2; installed add-on update/uninstall lifecycle acceptance remains open.
- [ ] Complete Rust-only and Python/Rust acceptance matrices. Latest Rust transport suite passed 20 with 1 ignored; Python/Rust fixture and deterministic chat/persistence acceptance passed 3. Startup/EOF/cancellation/server-saturation paths are covered, and shutdown responsiveness under fully saturated invocation capacity now passes. Bounded command admission and reserved control capacity have direct primitive-level coverage; process-level JSON-lines saturation, the full chat cancellation/switch/recovery matrix and add-on reload/uninstall acceptance remain open.
- [x] Run a real safe read-only MCP Bridge operation against the running NVDA process through the packaged manager, worker command adapter, Python catalog and ToolExecutor: discovered 31 tools, approved `list_loaded_addons` narrowly, and got a correlated successful result (`live-nvda-read-1`). This direct acceptance path did not exercise the installed assistant UI or keyboard approval flow.
- [ ] Verify keyboard approval/revocation, screen-reader responsiveness, and add-on reload using the installed assistant UI. Desktop automation helper initialization failed because its kernel assets path was unavailable; the installed Bridge's UI remains untouched.

### P10 — Final audit

- [ ] Review concurrency, lock ordering, resource limits, authorization, prompt injection, identity/generation, retry, secrets, UI thread affinity, accessibility and packaging.
- [ ] Run all commands from `AGENTS.md` and this phase spec after the latest changes; inspect actual package and Windows process cleanup results.
- [ ] Update IPC/security/production architecture and tool-system migration docs with evidence and deferred blockers.
- [ ] Report each P00–P10 status, files, tests, commit IDs, baseline/final counts, package impact, actual Windows/NVDA results and release readiness.

### Current follow-up evidence (2026-11-13)

- Latest fixes: `McpCatalogService` now coalesces tool-list notifications during an in-flight refresh and fences catalog publication/availability on disconnect, reconnect, retirement and shutdown revisions. Rust no longer uses RMCP `list_all_tools()`; `tools/list` pages are accumulated with cumulative count/serialized-byte checks, repeated-cursor detection and a 64-page cap. Regressions: `test_notification_during_refresh_coalesces_a_follow_up_catalog_read`, `test_disconnect_fences_inflight_notification_refresh`, and `bounded_catalog_stops_after_crossing_tool_count_limit`.
- Final checks after the end-to-end cancellation classification fix: `uv sync --locked`; Ruff clean; full pytest with packaged smoke and MCP fixture gates enabled: 1,318 passed, 2 skipped, 40 deselected; `tests/tools` 133 passed; Rust MCP formatting, Clippy `-D warnings`, and transport tests 19 passed/1 ignored; host `cargo check`; runtime supervisor 24 passed; Web UI 49 passed and build clean; SCons dry run/build; packaged worker smoke 2 passed; Python/Rust cross-language and chat/persistence acceptance 3 passed.
- Latest archive: 24,338,831 bytes, 1,038 entries, Rust manager 4,476,416 bytes; no test/fixture/bytecode entries. Windows hostile-grandchild Job Object cleanup remains verified by the Rust test suite. A live installed NVDA Bridge read-only call was previously successful. Keyboard/screen-reader UI validation and installed add-on reload/uninstall are pending the action-time confirmation for updating the installed profile with this build; the installer confirmation is currently open.

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
- Command admission was extracted into the same private helper used by `run_stdio` and directly tested: ordinary command capacity rejects the next admission at its bound, the independent control reserve remains available, and completed work releases capacity. This is a deterministic semaphore-level test; end-to-end saturation through piped JSON-lines remains a P02 gap.
- The installed NVDA add-on currently lacks `mcp_settings.py` and `mcp_manager.exe`; live keyboard/speech validation against the new UI is therefore not yet possible without installing the newly built package. The current source contains the new settings panel, but static UI tests are not a substitute for installed NVDA interaction.

## Baseline

The hardening baseline at `70eaaba60d246bce1728550b70fcc1fb1934d213` is recorded above. Phase 4 began from current HEAD `4a6e7ca`. The worktree also contains unrelated host JavaScript edits and untracked `.superpowers/`; these are user work and must be preserved.

## Plan review

The spec names one compatible production architecture and explicitly rejects a second policy system, UI-host ownership, and direct WebView execution. Therefore no competing implementation is being introduced. The task order preserves the stated security dependency: manager primitives first, then worker/Python execution, then catalog/UI/package integration. The supplied Phase 4 specification authorizes implementation, so execution proceeds in this order without a separate scope-selection pause.
