# Unified llama model manager and companions

Authorized by the user's request to implement the reviewed design end to end.
Reuse the existing dirty checkout and preserve prior changes; no automatic commit.

One main native configuration list includes external models, selected state,
file availability and runtime state. Search and selected details remain accessible.
Visible actions: Add model, Select/Locate, Load/Unload/Stop, Settings, More,
Refresh and Close. More holds Duplicate, Edit source/companions, Locate,
Remove configuration, verified file deletion and digest-bound preset import.

Add model has Local GGUF, Hugging Face, Existing downloads choices. Cached
weights are linked. HF resolution is explicit and asynchronous, displays artifact
and known size (unknown explicitly), and must not download on creation/selection.
Create keeps selection; Create and use selects without startup. Suggested names
remain editable. User inputs survive errors. Runtime and generation settings have
one entry point; defaults remain unpinned and effective observations are labelled.

Optional companions: vision projector, speculative draft or MTP GGUF. Store role,
source kind/reference/artifact/revision, ownership, local path and provenance.
Compatibility is unverified until the backend loads successfully. MTP is selected
explicitly via supported speculative mode, not inferred from names. One primary
GGUF plus explicit companions is supported; multipart primary weights remain
unsupported and must explain why. Companion local/cache/HF selection is explicit.
Worker resolves/downloads remote companions only during Load/first inference;
validate installed supported flags before launch and retain registrations on failure.
All file dependencies, including legacy mmproj/draft options, participate in shared
deletion protection. Never delete a referenced file from another configuration.

Load/Unload are application-owned operations with stable operation IDs, per-model
deduplication, cancellation and retained stage/error/status history. A closed dialog
detaches observers; Stop targets one operation. Disposable UI reads still cancel
on close. Reopening displays ongoing/completed operations. Unload is owned-server
only, bounded, model-specific, and confirms actual unloaded status. Application
shutdown cancels operations before worker teardown. Source/config mutation must
not race an active lifecycle operation. External endpoints remain selection-only.

Use native labelled controls, no single-letter shortcuts, stable keyboard focus,
explicit selected versus highlighted state, throttled stage announcements, Escape
dismissal and return focus. Runtime processes remain native-supervisor owned in
the worker. Existing worker job/event protocol is reused; no Rust/Svelte changes.
Tests exercise catalog, worker, HTTP and real wx boundaries and error/cancel paths.
Live NVDA speech/focus and real tensor compatibility remain manual acceptance.

Compatibility reference: installed llama-server build 10970 / bfdc32183 and its
tools/server/README.md, not unpinned upstream assumptions.
