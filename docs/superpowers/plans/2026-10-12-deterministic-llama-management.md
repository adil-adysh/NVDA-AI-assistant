# Deterministic llama.cpp model management

Approved brief: separate registration, file ownership, availability and runtime
state; centralize supported preset syntax; implement removal and owned-cache
deletion; serialize mutations and fence stale refreshes; test and package.

## Decisions

- User presets remain immutable input. Generate an add-on-owned effective preset,
  preserving unknown options and excluding removed registrations.
- A registration can be removed when its source file is missing. External server
  rows cannot be removed. Repeated removal is idempotent and lookup cannot import.
- llama.cpp's shared download cache is external. Cache deletion requires recorded
  add-on ownership and a worker-side containment check; no ownership inference.
- Stop the owned router before removal, fail if shutdown fails, clear an active
  selection, and suppress retired server identities until explicit reimport.
- Serialize catalog transactions across manager instances. Preserve legacy JSON
  catalogs; version the new manifest and roll back failed preset exports.
- Generated syntax supports preset version 1, local model, hf-repo/hf-file,
  context and reasoning. Reject unknown preset versions before launching.
- Keep this work in the existing authorized checkout and leave changes uncommitted.

## Execution ledger

- [x] Explicit state/actions and pure preset codec, with regression tests.
- [x] Catalog ownership, transactions, exact removal and migration.
- [x] Manager lifecycle, active selection and worker-owned cache deletion.
- [x] Accessible UI actions, feedback, focus and stale-refresh fencing.
- [x] Fresh review, regression suite, package build and documentation.

## Review and verification

Fresh source review identified stale source-preset snapshots, caller-selected cache
roots and failed status queries bypassing shutdown. All were reproduced and fixed;
reviewer rechecked and reported no remaining P1/P2 findings. Additional selection
race tests cover compare-and-set and preservation of a later in-memory selection.

Full package build and SCons dry run passed. Native supervisor: 24 tests passed.
The generated preset passed a real offline router smoke with installed build10970.
The full Python suite and built-NVDA integration tier are rerun on the final sources.
Packaged smoke requires the native extensions and verifies the cache deletion job
in both the isolated source bundle and the extracted add-on package.

Final verification: 1,010 Python tests passed, 2 skipped, 18 integration tests
excluded from the normal tier; 60 subtests passed. Built-NVDA integration:
18 passed. Native supervisor: 24 passed. Ruff, whitespace check, SCons dry run
and full package build passed. Packaged-worker, LiteRT and installed llama.cpp
smoke requirements were enabled for the full suite. No model inference or
weight download was performed. Output: AIAssistant-0.14.0.nvda-addon.

Exact-ID regressions additionally cover punctuation/case collisions, selection
clearing, lookup precedence and preservation of a surviving server identity.
Changes remain uncommitted.
