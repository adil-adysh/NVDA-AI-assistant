# Local Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record useful, privacy-safe local request metrics and task events through one bounded JSONL reporter, and accurately describe the setting.

**Architecture:** Instrument provider calls in `ProviderLLMService`; retain task lifecycle events from `BackgroundTaskRunner`. A shared reporter owns schema, allowlisting, serialization, locking, and rotation. Settings and docs describe the local opt-in behavior.

**Tech Stack:** Python, wxPython/NVDA settings UI, JSONL, pytest.

**Spec:** `docs/superpowers/specs/2026-11-21-observability-design.md`

## Global Constraints

- Keep provider/model operations off the NVDA event thread.
- Keep all user-facing strings translated with gettext.
- Keep logs local and opt-in; never log user content, secrets, URLs, paths, or raw exception messages.
- Keep file logging failures non-fatal to the operation being measured.

## Review Focus

- Provider exceptions and cancellation still propagate unchanged while producing safe records.
- A chat turn with tool follow-ups records each model call but not tool execution as a provider request.
- Multiple reporter instances writing concurrently do not interleave JSONL records.
- Rotation preserves the configured active path and only the configured small number of backups.
- A locked active file does not erase backups, and callback-derived task names remain identifiable after sanitization.
- Queued cancellation and already-completed futures never perform file I/O on the NVDA event thread.
- Disabled logging performs no filesystem writes.

---

### Task 1: Request record schema and reporter

**Files:**
- Modify: `addon/globalPlugins/AI-assistant/observability/metrics.py`
- Modify: `addon/globalPlugins/AI-assistant/observability/events.py`
- Modify: `addon/globalPlugins/AI-assistant/observability/reporter.py`
- Modify: `addon/globalPlugins/AI-assistant/ui/task_runner.py`
- Test: `tests/observability/test_events.py`
- Create: `tests/observability/test_reporter.py`

**Interfaces:** `RequestMetrics` represents one provider call; `FileMetricsReporter.report()` and `.report_event()` write versioned, allowlisted records.

- [ ] Write tests for record type/schema, field allowlisting and unsafe values.
- [ ] Write tests for locked-file rotation and off-thread task-event writes.
- [ ] Run focused tests and confirm they fail for the missing schema/rotation behavior.
- [ ] Implement safe record serialization, process-wide write locking, size rotation, and disabled-write behavior.
- [ ] Queue background task events away from callback threads; preserve stable names for local callback functions.
- [ ] Run the focused observability tests.

### Task 2: Instrument shared provider calls

**Files:**
- Modify: `addon/globalPlugins/AI-assistant/service/llm.py`
- Modify: `addon/globalPlugins/AI-assistant/plugin/factory.py`
- Modify: `addon/globalPlugins/AI-assistant/service/base.py`
- Modify: `addon/globalPlugins/AI-assistant/service/chat/coordinator.py`
- Test: `tests/service/test_llm_observability.py`

**Interfaces:** `ProviderLLMService(provider, tool_executor=None, metrics_reporter=None)` accepts the reporter; request methods tag request kinds and measure each provider call.

- [ ] Write tests for success, provider failure, cancellation, and multiple chat model calls; assert no raw exception or content is recorded.
- [ ] Run focused tests and confirm expected failures.
- [ ] Inject the shared reporter from the composition root, instrument provider calls, and remove unused coordinator metrics hooks and metric subclasses.
- [ ] Run focused LLM and existing coordinator tests.

### Task 3: Settings and user documentation

**Files:**
- Modify: `addon/globalPlugins/AI-assistant/ui/settings_panel.py`
- Modify: `addon/globalPlugins/AI-assistant/observability/metrics.py`
- Modify: `readme.md`
- Test: `tests/ui/test_diagnostics_settings.py` (or the nearest existing settings test module)

- [ ] Add focused checks for default-off state, path collection, and accurate accessible labels/help text where the current UI test harness supports it.
- [ ] Run the focused tests and confirm expected failures.
- [ ] Update translated diagnostics copy and README wording to describe local request/task metadata and excluded content.
- [ ] Run focused UI/documentation checks.

### Task 4: Full verification

**Files:** No additional implementation files.

- [ ] Run `uv run ruff check .`.
- [ ] Run `uv run pytest`.
- [ ] Inspect the final diff for privacy fields, retention behavior, protocol/API drift, and untracked files.
