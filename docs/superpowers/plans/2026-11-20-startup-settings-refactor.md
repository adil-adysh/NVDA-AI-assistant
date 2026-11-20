# Startup settings refactor implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the Runtime settings tab with two clear per-provider startup choices and a General request timeout.

**Architecture:** Provider configuration owns two-choice local startup preferences. Worker and server ownership, startup guards, provider switching and shutdown fences remain in existing application services.

**Tech stack:** Python, wxPython and existing configuration store.

**Approved design:** User-approved conversation design: remove Runtime tab; local provider configuration offers Start when needed or Start when NVDA starts; only active provider starts; worker preparation is internal; timeout moves to General. User clarified no preference migration or compatibility is needed because these settings are unreleased.

## Constraints and review focus

Startup changes apply at the next NVDA start and never activate an inactive provider. Cancel and Test Connection do not save startup preferences. Invalid selection keeps the dialog open and focuses the control. Unsupported stored modes use the on-demand default without migration. Main settings Apply must not overwrite a startup preference saved in a provider dialog.

## Tasks

- [x] Add failing config validation tests, provider startup draft/save/cancel tests, General timeout validation and removed-tab tests.
- [x] Limit supported startup modes to lazy/server; remove old booleans, accessors and worker-only startup path.
- [x] Add translated accessible startup choice only to local provider Configure dialogs, validate before saving, save without activating providers.
- [x] Move request timeout to General; remove Runtime tab, startup fields and persistence from main settings.
- [x] Simplify startup orchestration to launch servers only when configured, with existing active-provider and shutdown guards.
- [x] Update affected tests and documentation; run focused suites, Ruff, full Python suite and build dry run.
- [x] Review changes independently and address concrete findings.

Work stays in the shared checkout to preserve ongoing edits. No installation, NVDA restart or commit is requested.
