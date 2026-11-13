# llama.cpp Model Management UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users distinguish configurations, downloaded assets and server models,
reuse cached weights, and manage models accessibly with accurate lifecycle feedback.

**Architecture:** The worker discovers/verifies assets; Python catalogs and a shared
presentation policy reconcile configurations, assets and endpoint observations.
A provider-specific wx view consumes explicit actions while the existing worker
transport and native runtime supervisor retain lifecycle authority.

**Tech Stack:** Python 3.13, wxPython/NVDA, existing JSON worker jobs, Rust runtime
supervisor, pytest through uv. No new native UI or frontend dependency.

**Spec:** `docs/superpowers/specs/2026-10-12-llama-model-management-ux-design.md`

## Delivery status

Tasks 1–6 are implemented. The final review's five P2 findings have regression
coverage and fixes. Validation: 1,067 Python tests passed (two skipped), 19 NVDA
integration tests passed, Ruff clean, SCons dry-run and package build successful.
Packaged-worker and real-router verification results are recorded in the ledger.

Live NVDA speech/focus acceptance remains pending using the development checklist.
Per-task commit steps remain unchecked deliberately: this checkout includes prior
uncommitted work, so implementation and review were retained together rather than
creating partial commits that mix unrelated changes. Their technical test/review
portions are complete. The original checklists below retain those explicit gaps.

## Global Constraints

- `models.json` remains authoritative; original presets and model files are unchanged.
- Cache discovery is local-only and does not start an inference server.
- Speech, focus, settings policy and NVDA object access remain in NVDA.
- Managed process lifecycle remains native-supervisor owned through the worker.
- Shared cache deletion and broader shard/multi-file import are outside this delivery.
- All user-facing strings use literal gettext templates; tests live under `tests/`.
- Preserve current generic-provider behavior and source/ownership verification.
- Implementation was authorized after plan review; live NVDA speech/focus acceptance remains a manual release check.

## Review Focus

- Cache cleanup between discovery and Create: revalidation fails without a registration.
- Several configurations for one blob: remove/refresh never merges IDs or deletes files.
- Remote/external endpoint paths: never treat server-reported paths as local cache proof.
- Focus in Search/settings while refresh completes: retain focus and reject late callbacks.
- Unsupported saved flags after runtime downgrade: expose/reset values without silent loss.

## File and interface map

Create `core/model_assets.py` for worker-safe DTOs and `worker/executors/model_assets.py`
for discovery/verification. Create `providers/llama_catalog.py` for reconciliation and
`ui/llama_model_manager.py` for the provider-specific view. Keep persisted records in
`providers/runtime/llama_models.py`, manager operations in `providers/llama_manager.py`,
and runtime tuning in `ui/llama_runtime_dialog.py`. Reuse generic generation settings.

`ModelAssetSnapshot` fields: `asset_id: str`, `token: str`, `path: str`,
`source: str` (llama_cache/hf_hub/user_folder), `availability: str`
(present/missing/incomplete/unknown), `size_bytes: int | None`,
`repository: str | None`, `revision: str | None`, `artifact: str | None`,
`quantization: str | None`, `capabilities: tuple[str, ...]`,
`file_identity: str`. IDs/tokens are worker-issued; caller filenames cannot establish
ownership or provenance. Add explicit to_dict/from_dict methods for transport.

`ModelDiscoverySnapshot`: `generation: int`, `assets: tuple[ModelAssetSnapshot, ...]`,
`errors: dict[str, str]` by root, `scanned_at: float`. Errors are separate from an
empty successful result. Worker file verification returns a fresh ModelAssetSnapshot.

`LlamaModelEntry` wraps existing `ManagedModel` with `kind: str`
(configuration/downloaded/server), `asset_id: str | None`,
`configuration_ids: tuple[str, ...]`, `runtime: str`, `stale: bool`.
Maintain existing IDs/aliases for migrated records; add optional persisted
`display_name` and `asset_id`, defaulting to model_id/no asset for legacy records.

### Task 1: Accurate catalog states and a shared action policy

**Files:** create `core/model_assets.py`, `providers/llama_catalog.py`;
modify `providers/model_manager.py`, `providers/llama_manager.py`,
`providers/runtime/llama_models.py`, `providers/adapters/llama_cpp.py`;
test `tests/providers/test_llama_catalog_presentation.py`.

**Interfaces:** produce `reconcile_llama_entries(records, assets, server_items,
*, endpoint_owned: bool, stale: bool = False) -> list[LlamaModelEntry]` and
`selectable_llama_entries(entries) -> list[LlamaModelEntry]`. Extend explicit actions
with CREATE_CONFIGURATION, EDIT_RUNTIME, EDIT_GENERATION and LOCATE_SOURCE.
Existing shared `ModelState` behavior must not be globally reinterpreted.

- [x] Write tests: an unloaded server item is not loaded; a remote reference is
  selectable with download-on-first-use copy; a missing local source is removable
  but not selectable; an external endpoint path is not a verified local asset.
- [x] Add the shared-blob test: configurations A/B retain separate exact IDs,
  settings and selection while referencing one asset ID.
- [x] Run `uv run pytest tests/providers/test_llama_catalog_presentation.py -q`; confirm failures.
- [x] Implement the DTOs, pure reconciler and manager integration. Decode all
  upstream status values explicitly; unknown stays unknown. Capabilities carry
  confidence/unknown copy rather than filename guesses.
- [ ] Run the new tests and existing deterministic-management/catalog-refresh tests;
  review changes and commit only this task's paths after validation.

### Task 2: Worker cache discovery and verified asset reuse

**Files:** create `worker/executors/model_assets.py`;
modify `worker/runtime_commands.py`, `core/job/operations.py`,
`providers/llama_manager.py`, `config/settings.py`;
test `tests/worker/test_model_asset_discovery.py`,
`tests/providers/test_llama_cached_configuration.py`.

**Interfaces:** worker `discover_model_assets(roots: list[dict[str, str]],
generation: int) -> ModelDiscoverySnapshot` and
`verify_model_asset(token: str) -> ModelAssetSnapshot`. Add runtime commands
`llama_discover_assets` and `llama_verify_asset` to producer/consumer allowlists.
Manager `discover_assets() -> ModelDiscoverySnapshot` and
`create_configuration_from_asset(token: str, model_id: str, display_name: str,
options: dict[str, str], *, select: bool = False) -> str`.

- [x] Write discovery fixtures for LLAMA_CACHE, verified HF snapshots/blob links,
  duplicate paths, incomplete files, corrupt headers, inaccessible roots and
  unsupported shard/projector arrangements. Assert zero network/server starts.
- [x] Test cancellation, health and shutdown responsiveness during a deliberately
  slow scan, and per-root errors retaining other successful assets.
- [ ] Test file deletion/replacement between scan and Create: no commit, no copy,
  no download; two configurations share weights; external server paths are rejected.
- [x] Run focused tests to confirm failures, then implement bounded/cancellable
  scanning in a worker execution lane. Resolve explicit roots/environment there;
  unknown runtime roots require folder selection. Persist scan configuration only.
- [ ] Use worker verification immediately before catalog commit; check stable ID
  collisions, preserve ownership and return the created ID. No UI-side file scanning.
- [ ] Run focused tests plus worker lifecycle tests; review and commit task paths.

### Task 3: One accessible manager with three views

**Files:** create `ui/llama_model_manager.py`;
modify `ui/model_manager.py` (factory dispatch only),
`providers/model_manager.py` (configuration-management feature capability);
test `tests/ui/test_llama_model_manager_views.py`.

**Interfaces:** `LlamaModelsDialog(parent, provider)` consumes Task 1 entries and
Task 2 discovery methods. Factory dispatch uses an explicit provider capability,
not provider/network logic embedded in widgets.

- [x] Write tests for named columns, three view filters, search, empty-state Add/
  Browse actions, shared-asset relations and contextual button eligibility.
- [x] Test Enter invokes the primary action, visibility is a labelled control,
  decorative headings are not selectable, and Escape closes safely.
- [x] Test refresh while focus is in Search; failure keeps selected ID, scroll and
  stale rows; close/filter changes discard late results without reopening the dialog.
- [x] Run tests to confirm failures, implement the view, and keep read completion
  separate from mutation completion. Only durable mutations invalidate model caches.
- [ ] Verify resulting-row selection after Create/Remove without stealing focus
  on passive reads. Run generic-provider UI regressions; review and commit.

### Task 4: Configuration creation, naming and preset migration preview

**Files:** create `ui/llama_configuration_dialog.py`;
modify `providers/runtime/llama_models.py`, `providers/llama_manager.py`,
`ui/llama_model_manager.py`, `core/llama_preset.py`;
test `tests/providers/test_llama_configuration_transactions.py`,
`tests/ui/test_llama_configuration_flow.py`.

**Interfaces:** `preview_preset_import(path: str) -> PresetImportPreview` and
`commit_preset_import(preview: PresetImportPreview, *, replace_ids: tuple[str, ...])
-> PresetImportSummary`. Preview fields: source path, content digest, parsed immutable
records, replacement IDs, unsupported section/key pairs; commit verifies digest.
Unsupported previews are reviewable but cannot commit. Friendly names do not change
existing inference IDs. Add/duplicate configuration routes through manager methods.

- [x] Write tests for local/HF/cache creation, friendly name versus stable ID,
  explicit collision handling and Create versus Create and use.
- [x] Test unsupported migration, Cancel and changed source after preview: catalog,
  selection and original file stay unchanged; replace only acknowledged IDs.
- [x] Test legacy registrations load with display_name=model_id and unchanged aliases.
- [ ] Run failing tests; implement one source-summary/name/settings flow, explicit
  replace confirmation and background preview/commit. Registration feedback never
  claims a download occurred. Imported source files remain one-time input.
- [ ] Run migration/deterministic-management tests and UI flows; review and commit.

### Task 5: Settings clarity, preparation and recovery

**Files:** modify `ui/llama_runtime_dialog.py`, `ui/llama_model_manager.py`,
`providers/llama_manager.py`, `ui/download_progress.py` only for shared cancellation
copy if needed; test `tests/ui/test_llama_runtime_settings_accessibility.py`,
`tests/providers/test_llama_model_recovery.py`.

**Interfaces:** `prepare_configuration(model_id: str, on_progress,
cancel_event) -> None` delegates to existing native-owned readiness;
`relocate_configuration(model_id: str, source: str) -> None` preserves ID/settings
and validates the replacement source. Runtime-settings presenter supplies each
field's stored/effective value, origin, support and validation error.

- [x] Write tests for Basic/Advanced grouping, runtime allocation versus request
  context labels, visible imported values and per-field reset after downgrade.
- [x] Test unsupported MoE flags disable both placement and dependent layer count;
  reset summaries include hidden imported options; errors focus the offending control.
- [x] Test preparation cancellation is stopped rather than failed, only relevant
  stage feedback is spoken, and success says Loaded only after authoritative status.
- [x] Test missing asset → Locate files recovery preserves ID/other configurations;
  failures offer Retry/Edit settings/Choose another model without deleting weights.
- [x] Run failing tests; implement presenters and recovery actions using existing
  worker/native lifecycle. Avoid loading during browsing or active selection.
- [ ] Run runtime-settings, cancellation and readiness tests; review and commit.

### Task 6: Consistent selection, release verification and user documentation

**Files:** modify `ui/settings_panel.py`, `plugin/layer_mode.py` or its existing
selection service, `service/provider_catalog.py`, `plugin/presenter.py` where
selection labels are produced; update `docs/architecture-current.md`,
`docs/development.md`, `AGENTS.md`;
test `tests/ui/test_llama_selection_consistency.py` and packaged-worker smoke tests.

**Interfaces:** all selectors consume Task 1's selectable policy, friendly labels
and exact underlying IDs. Use existing host protocol fields; if new fields prove
necessary, align Python/Rust/Svelte together and add protocol regression coverage.

- [x] Write tests showing manager/settings/gesture selection agree; missing active
  configurations appear explicitly unavailable but remain manageable; cached assets
  never become active choices until configured; late provider results are fenced.
- [x] Add packaged worker discovery/verification/Create smoke tests from outside the
  checkout with temporary cache roots and no network/inference server.
- [x] Implement shared selection integration, accurate setup/startup help and docs.
  Keep legacy IDs, other providers and the external-server workflow working.
- [x] Run `uv run ruff check .`, `uv run pytest`, `uv run pytest -m nvda_integration`,
  `git diff --check` and `uv run scons --dry-run`. Run relevant native/Web UI checks
  only if those layers changed. Build `uv run scons` after DLL-loading tests finish.
- [x] Run packaged smoke with NVDA_AI_REQUIRE_PACKAGED_TESTS=1 and the offline router
  smoke with NVDA_AI_REQUIRE_LLAMA_TESTS=1; require passes rather than skips.
- [ ] Perform live NVDA keyboard-only acceptance: first setup, all views/headers,
  cache Create, dual configurations, defaults/reset, focus during slow refresh,
  cancellation, failures, import preview, removal and Escape from every dialog.
  Record actual announcements/focus and fix discrepancies before completion.
- [ ] Review the whole diff against the spec, document validation and commit only
  reviewed work; do not automatically publish or include unrelated pending changes.

## Delivery order and checkpoints

Tasks 1–2 establish reliable state and cache reuse; Task 3 makes them accessible;
Tasks 4–5 complete configuration/recovery journeys; Task 6 reconciles selection and
release validation. Each task is independently testable. Prefer native execution
in this chat because the tasks share DTOs and policies; no parallel agent work is
required. Review this plan before starting implementation.
