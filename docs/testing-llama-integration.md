# llama.cpp integration coverage

October 13 follow-up: the unified list/Add flow, retained Tasks, companion records,
HF lazy resolution, observed per-model Unload, shared dependency deletion protection,
offline companion reuse and llama request seed have additional regression coverage.
Current automated totals: 1,155 Python tests and 40 NVDA integration tests passed;
two normal-suite skips. Required package/router smoke: three passed. See
`docs/superpowers/plans/2026-10-13-unified-llama-manager.md` for delivery evidence.

The tests follow user journeys across boundaries. `tests/support/llama_flow.py`
wires the real model manager, catalog, JSON persistence, asset scanner, preset
codec and worker command dispatcher. Only process lifecycle is replaced, so these
journeys remain offline and cannot start an inference server or touch user models.
Per-model sampling and application settings are isolated to each test.

`tests/support/llama_http.py` supplies a deterministic loopback HTTP server, not an
HTTP client mock. HTTP tests exercise the production urllib boundary; inference
tests exercise the bundled native `llm_client` and the real llama provider adapter.
These are protocol-integration checks, not model-quality or tensor-validation tests.

## Workflow matrix

| Supported flow | Coverage |
| --- | --- |
| Local file, HF variant and explicit artifact registration; first-use startup | `tests/integration/test_llama_model_journeys.py`, `test_llama_inference_http.py` |
| Local/HF/llama cache discovery, provenance, deduplication, changed files, expired tokens and cancellation | `tests/worker/test_model_asset_discovery.py`, `tests/integration/test_llama_model_journeys.py`, `tests/worker/test_runtime_jobs.py` |
| Cache Create and use without copying, downloading or startup | Model journeys, real-dialog flows and `tests/build/test_worker_bundle_smoke.py` |
| Named duplicate, shared weights, generation copy, runtime divergence, sampling-save rollback | Model journeys, `tests/providers/test_llama_model_recovery.py`, and disk persistence in `tests/config/test_model_config.py` |
| Missing file, unavailable selection, Locate source and preserve settings | Model journeys, real-dialog flows, `tests/ui/test_llama_selection_consistency.py` |
| Basic/Advanced runtime settings, KV/MoE, capability updates, defaults, per-field unsupported reset, validation | Model journeys, real-dialog flows, `tests/ui/test_llama_runtime_options.py`, `test_llama_runtime_settings_accessibility.py` |
| Installed-runtime downgrade blocks startup, keeps overrides, and allows reset/retry | Model journeys and deterministic management tests |
| One-time import, shared defaults, explicit replacement, Cancel, unsupported syntax/source, source/catalog drift | Model journeys, real-dialog flows, `tests/providers/test_llama_configuration_transactions.py`, `test_llama_preset_migration.py` |
| Remove versus delete owned cache; external models are usable and protected | Model journeys, real-dialog flows, `tests/providers/test_deterministic_llama_management.py`, packaged smoke |
| Visibility persistence, exact identities and selection across consumers | Real-dialog flows, selection consistency and deterministic management tests |
| `/models` status metadata, 404 legacy fallback, invalid JSON/UTF-8/schema, nested status/architecture normalization, stale retention and recovery | `tests/integration/test_llama_http_flows.py`, model journeys |
| Prepare loaded versus unloaded, late cancelled cleanup, retry, original-error preservation, explicit loaded feedback | HTTP flows, real-dialog flows, `tests/worker/test_llama_prepare_model.py` |
| Ordinary chat, streaming summaries, schema summaries, images, Stop with partial response, HTTP failure | `tests/integration/test_llama_inference_http.py` |
| Busy list activation, edit-after-create, search/selection retention, Stop/Close during scan, Escape button route | `tests/integration/test_llama_dialog_flows.py`, `tests/ui/test_llama_model_manager_views.py` |
| Native lifecycle startup/restart, crash recovery, health, shutdown during slow work | `tests/worker/test_llama_worker*.py`, `test_runtime_jobs.py`, `tests/integration/test_local_provider_lifecycle.py` |
| Real installed llama router accepts generated presets | `tests/build/test_llama_preset_smoke.py` |

## Running the tests

Run the normal suite with `uv run pytest`. The new offline integration modules
are part of that suite and require the built bundled native HTTP client, as do
the existing provider tests. They use temporary folders and loopback HTTP only.

Run `uv run pytest -m nvda_integration` for actual wx dialogs with the pinned,
built NVDA GUI helpers and the real background runner. Modal responses stand in
for human input; process-owned speech is captured. These tests execute real
controls and persistence, not replacement widget implementations.

After DLL-loading tests finish, build with `uv run scons`, then require the package
and real-router checks in PowerShell:

```powershell
$env:NVDA_AI_REQUIRE_PACKAGED_TESTS = '1'
$env:NVDA_AI_REQUIRE_LLAMA_TESTS = '1'
uv run pytest tests/build/test_worker_bundle_smoke.py tests/build/test_llama_preset_smoke.py
```

The worker smoke exercises both the source bundle and the `.nvda-addon` from
outside the checkout, including asset verification, Create/use, runtime edits,
one-time imports/removal, mutation rejection, and owned cache deletion.

Live NVDA speech, keyboard focus, actual Escape keystrokes, real model loading,
downloads/authentication and inference quality still require the manual journeys
in `docs/development.md`. Hidden-window tests do not certify screen-reader output
or every OS focus edge case. Unknown model metadata remains explicit; discovery
checks identity/basic format rather than validating every tensor.

## Validation record — 2026-10-12

This audit added 74 scenarios: 37 model journeys, 12 HTTP/runtime cases,
6 native-client inference cases, 18 real-dialog cases and one preparation cleanup
regression. It also extended both packaged-worker smoke variants.

Fresh verification: `uv run pytest` — 1,123 passed, two skipped;
`uv run pytest -m nvda_integration` — 37 passed; Ruff and diff checks passed;
SCons dry-run/full build passed. Required packaged-worker and real-router smoke —
three passed, no skips. Live NVDA acceptance remains as described above.

Regression fixes cover failed cache roots losing prior rows, import routes bypassing
single-file policy, ambiguous/unnormalized preset sources, unsafe IDs, malformed
catalog/status/architecture data, repeated loading of an already-loaded model,
cleanup masking the original loading error, and busy list activation opening a
second dialog. Each failing reproduction passed after its corresponding fix.
