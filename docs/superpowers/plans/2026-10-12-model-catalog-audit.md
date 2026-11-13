# Model catalog and llama.cpp audit

Authorized scope: repair existing import, preset and refresh flows across providers,
preserving worker isolation and the native runtime supervisor lifecycle.

## Confirmed defects repaired

- Invalidated fetches notified subscribers and synchronous callers with stale models.
- Cache-wide invalidation failed to advance newly populated provider generations.
- Waiting callers could retry under the catalog lock.
- Capability lookup cached provisional empty flags during refresh.
- Provider IDs reused catalogs after endpoint or credential changes.
- Cloud manager's second cache hid refreshes and swallowed discovery failures.
- HTTP failures were treated as successful empty catalogs.
- Inference readiness blocked offline local catalog discovery.
- LiteRT authoritative discovery cached worker unavailability as an empty registry.
- llama.cpp refresh reused server-model cache; failed refresh retained stale models.
- llama import lost quantization and artifact fields when re-parsing the repository.
- Revision and file selectors were misinterpreted as quantization variants.
- Preset generation dropped selected artifacts and retained obsolete hf-file values.
- Manifest records hid external preset source and metadata edits.
- Global preset metadata and relative model paths were not resolved consistently.
- Invalid section IDs could be persisted but omitted at startup.
- Worker preset configuration failures were swallowed before server launch.

The pure core/llama_preset.py replaces duplicated preset builders. Runtime startup
remains owned by the worker's native supervisor. Cloud managers use the central
catalog directly. Catalog configuration identities are stored as digests and never
logged; capability flags survive loading and discovery failure. Deferred presenter
callbacks check the catalog generation before updating the UI.

Upstream reference checked:
https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
The documented CLI supports hf-repo and hf-file, without a Hugging Face revision
selector. The current manager rejects non-main revisions before registration.

## Validation

- New regression tests reproduced failures before implementation.
- Full suite: 982 passed, 2 skipped, 18 deselected, 60 subtests passed.
- Built-NVDA integration: 18 passed, 6 deselected.
- Ruff, git diff whitespace check, SCons dry run and full package build passed.
- Full suite required packaged-worker and LiteRT smoke tests.

No model weights were downloaded for this audit. Live llama.cpp inference was not
tested. The changes are uncommitted.
