# Local Observability Design

## Intent

Make the Diagnostics settings accurate and useful by recording opt-in request measurements alongside the existing background task lifecycle events. This helps users diagnose slow or failing model operations. The add-on writes only to the user-configured file path and does not upload records.

## Goals

- Record one request measurement for every provider call made by `ProviderLLMService`, including chat follow-up calls.
- Preserve background UI task lifecycle records as a distinct record type.
- Use one versioned JSONL file, a thread-safe writer, and bounded file rotation.
- Keep task-event file work off the NVDA event and task-completion threads through a bounded daemon queue; if it is full, drop a diagnostic record rather than blocking application work.
- Record only allowlisted metadata: operation type, provider, returned model when available, duration, outcome, and exception type. Never write prompt/response/image content, credentials, endpoint URLs, local paths, or raw exception messages.
- Keep logging disabled by default and explain the data, configured destination, and lack of automatic uploads in the Diagnostics panel and README.
- Remove the unused request-metrics extension points and metric variants that do not participate in recording.

## Non-goals

- Uploading telemetry or introducing analytics services.
- Recording model input/output sizes or estimating token counts.
- Adding user-facing log browsing, export, or deletion workflows.
- Reworking provider, chat, or UI architecture.

## Approaches

- Keep separate request and task loggers/files: clear separation, but duplicates path, locking, rotation, and user settings.
- Use one versioned local log with distinct `request_metric` and `task_event` records: one storage path and lifecycle, with record types retaining their meaning. **Chosen** for simplicity and future schema extension.
- Rename the current setting to background diagnostics only: accurate for today, but fails the documented request-metrics use case.

## Design

`ProviderLLMService` measures provider calls at the shared `_request` boundary and submits metadata records to the reporter. Each chat model invocation is measured separately; tool execution itself is not a provider request. Existing `BackgroundTaskRunner` lifecycle events use the same reporter with a distinct record type and a bounded daemon queue so callback paths never perform file I/O. The reporter applies a fixed field allowlist, serializes writes under a process-wide lock, and first reserves the active JSONL file before rotating backups at a fixed size, retaining a small fixed number of backups. If Windows blocks an active-file rename, the reporter leaves existing backups intact. Reporting failures remain non-fatal to model and UI operations.

The Diagnostics panel describes the opt-in request and background-task records, identifies excluded content, and labels the configured JSONL path without implying that a user-configured network path stays on the local computer. The README uses the same wording. Tests cover schema and redaction, request success/failure/cancellation, task events, concurrent writes, rotation and locked-file behavior, asynchronous task reporting, and settings-facing configuration behavior where the UI can be exercised safely.
