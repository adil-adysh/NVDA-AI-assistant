# Provider List Accessibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make provider and model lists predictable and fully keyboard and screen-reader accessible, with composable model filters and explicit model state actions.

**Architecture:** Keep the native wx provider/model dialogs and their existing service/store boundaries. Put model filter matching in a small pure helper that can be tested without constructing NVDA windows; dialogs render its results and own accessible focus/selection behavior.

**Tech Stack:** Python 3.13, wxPython, pytest, NVDA add-on UI.

**Spec:** `docs/superpowers/specs/2026-11-20-provider-list-accessibility-design.md`

## Global Constraints

- Python user-facing strings must use `_()` and translatable templates must be translated before `.format(...)`.
- UI code must use existing provider services and model visibility store; do not call providers directly.
- Tests live under top-level `tests/` and use shared loaders from `tests/support/bootstrap.py`.
- Preserve the current WebView/native UI boundary and do not add dependencies.
- Preserve unrelated user changes; do not remove unrelated or still-valid tests.

## Review Focus

- Every enabled-state and availability filter combination uses AND semantics and retains the correct models.
- `READY`, `DOWNLOADED`, and `REGISTERED` all match Available; `NOT_DOWNLOADED`, `DOWNLOADING`, and `FAILED` remain separately filterable.
- A disabled active model remains visible under the default All/All filters and is selected on first load.
- Enabling or disabling a model that no longer matches the current filters clears selection and disables model-specific actions without leaving stale state.
- Refreshes preserve selection and restore focus only when the previously focused control is displaced.

---

### Task 1: Define and test composable model filters

**Files:**
- Create: `addon/globalPlugins/AI-assistant/ui/model_filters.py`
- Create: `tests/ui/test_model_filters.py`

**Interfaces:**
- Produces `matches_model_filters(state: ModelState, enabled: bool, enabled_filter: str, availability_filter: str) -> bool`.
- Filter values are stable UI identifiers: enabled state `all`, `enabled`, `disabled`; availability `all`, `available`, `not_downloaded`, `downloading`, `failed`.

- [x] **Step 1: Write failing parameterized tests** for every `ModelState` mapping and representative AND combinations, including disabled cloud-ready and enabled not-downloaded models.
- [x] **Step 2: Run `uv run pytest tests/ui/test_model_filters.py -q`** and confirm the tests fail because the helper is absent.
- [x] **Step 3: Implement the pure matching helper** with Available mapping to `READY`, `DOWNLOADED`, and `REGISTERED`, and one-to-one mappings for the other availability states.
- [x] **Step 4: Run the focused tests** and confirm all filter combinations pass.

### Task 2: Make the provider model manager accessible

**Files:**
- Modify: `addon/globalPlugins/AI-assistant/ui/model_manager.py`
- Create or extend: `tests/ui/test_provider_model_accessibility.py`

**Interfaces:**
- Consumes `matches_model_filters` from Task 1.
- Provides a labeled Enabled state choice, a labeled Availability choice, an Enabled text column, an Active text column, and explicit Enable/Disable buttons.

- [x] **Step 1: Add failing UI contract tests** for both labeled filters, All/All defaults, named state columns, separate Enable/Disable controls, selection-dependent button states, active-model initial selection/focus, and removal of mouse/glyph/Enter toggling.
- [x] **Step 2: Run the focused tests** and confirm they fail against the current checkbox-glyph and “Show disabled models” UI.
- [x] **Step 3: Replace the legacy controls** with the two filters, textual Enabled/Active columns, and keyboard-operable Enable/Disable buttons. Filter rows through the helper; keep active selection on initial load and preserve it through refresh when still visible. Clear selection and update status when filters or actions hide the selected item.
- [x] **Step 4: Run the focused tests** and confirm the new controls, selection, and filter behavior pass.

### Task 3: Fix provider and preset selection/focus and control names

**Files:**
- Modify: `addon/globalPlugins/AI-assistant/ui/provider_dialog.py`
- Modify: `addon/globalPlugins/AI-assistant/ui/llama_model_manager.py`
- Modify: `addon/globalPlugins/AI-assistant/ui/settings_panel.py`
- Extend: `tests/ui/test_provider_model_accessibility.py`

**Interfaces:**
- No provider APIs change. Selection remains backed by existing `ProviderInfo`, preset records, and settings values.

- [x] **Step 1: Add failing tests** for active provider selection/focus on first open, provider row selection/focus restoration after refresh, active preset selection/focus on first load and preservation on refresh, and explicit accessible names for the General settings provider/model controls.
- [x] **Step 2: Run the focused tests** and confirm they fail against the current implicit focus and unnamed controls.
- [x] **Step 3: Implement initial and refresh focus behavior** without stealing focus from unrelated controls; name the provider choice and active-model combo according to their visible labels.
- [x] **Step 4: Run the focused tests** and confirm these behaviors pass.

### Task 4: Verify the complete change and retire obsolete UI behavior

**Files:**
- Modify only implementation and tests from Tasks 1–3 as needed.

- [x] **Step 1: Remove obsolete assertions or handlers only if they specifically require simulated checkbox glyph toggling or the old Show disabled checkbox.** Keep all unrelated legacy coverage.
- [x] **Step 2: Run `uv run pytest tests/ui/test_model_filters.py tests/ui/test_provider_model_accessibility.py tests/ui/test_settings_drafts.py tests/ui/test_settings_panel.py -q`.**
- [x] **Step 3: Run `uv run ruff check .` and the full `uv run pytest` suite.**
- [x] **Step 4: Review `git diff` and confirm only the approved design, its implementation/tests/plan, and pre-existing user changes are present.**
