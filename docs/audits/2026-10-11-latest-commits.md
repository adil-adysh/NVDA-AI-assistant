# Latest-commit audit — 11 October 2026

## Scope

Reviewed the recent local-model migration series through `af1cc8f`, tracing the
worker/client, download/install, application-composition, native-runtime, and
model-management boundaries. Also inspected the preceding llama model-catalog
changes. This is a targeted audit of those features, not an exhaustive review
of every provider or Web UI component.

Existing changes under `.agents/` and `ORIGINAL_REQUEST.md` were preserved.

## Reproduced defects repaired

| Area | Before | Repair / regression coverage |
| --- | --- | --- |
| Worker download client | Production passes `WorkerClient`; downloader calls missing `subscribe_progress` on it. | Resolve `get_job_client()`; real named-pipe download test. |
| Download completeness | EOF before advertised Content-Length still produces a completed file. | Validate transferred length in worker and direct fallback. |
| Range resume | A 206 response for a different offset is appended to the cached prefix. | Validate Content-Range start, end, length, and total before writing. |
| Expected model size | Unknown-total range responses override an already-known expected size. | Preserve known size; test that 8 bytes cannot satisfy expected size 12. |
| Direct 416 handling | Any HTTP 416 means “already complete,” including a four-byte partial file when the server total is eight. | Require server total, requested offset, and on-disk size to match. |
| Cached model verification | Any existing destination bypasses requested SHA-256 verification. | Verify cached contents and propagate failure/cancellation without deleting the existing file. |
| Fast job completion | Late submission acknowledgement replaces a completed snapshot with QUEUED and drops its result. | Only advance a snapshot still in SUBMITTED. |
| Worker bundle installation | Previous runtime is removed before copying its replacement. | Stage on destination filesystem; rename with rollback; retain recoverable backup if rollback fails. |
| Direct bundle installation | A failed staging copy deletes the previous runtime. | Stage a complete copy before touching the installed runtime; rename with rollback. |
| Installation cancellation | Cancellation just before installation still replaces the runtime. | Check cancellation before the worker installer commits. |
| Bundle manifest | Malformed JSON is logged and ignored, bypassing declared file validation. | Reject malformed manifest structures before installation. |
| Manifest file paths | Hash verification can read an absolute path outside the extracted bundle. | Require each resolved manifest file to remain inside the extracted root. |
| Worker restart | New worker always reports generation 1; supervisor generation 2 discards its heartbeat and times out. | Pass generation at launch and set worker generation before serving. |
| Source launch | Default entry point resolution depends on working directory. | Resolve repository source entry point from supervisor location. |

Tests are under top-level `tests/`, with isolated shared-bootstrap namespaces.
The independent reviewer caught the unknown-total expected-size case; it has a
reproduced regression test and repair. Direct-download validation was also
reviewed, and no new actionable defects were identified in that diff.

## Architectural findings

### Repaired P1: Managed local server production startup was disconnected

Before this repair, `plugin/application.py` and `plugin/factory.py` never instantiate/start/register a
`WorkerSupervisor`. Both provider supervisors' `_get_native()` methods return
only explicitly injected objects, and no production caller injects one.
Consequently default managed LiteRT/llama readiness reaches “Worker process is
not available.” Existing lifecycle tests exercise injected supervisors/clients,
so a passing suite does not establish working production composition.

The previous build also omits a standalone worker executable, while source launch
uses `sys.executable`; inside NVDA this is NVDA's executable, not a Python CLI.
Starting the existing source launcher from application initialization alone does
not repair installed add-ons.

The user selected a packaged worker with lazy server startup. The written design
is `docs/superpowers/specs/2026-10-11-packaged-worker-startup-design.md`.
Implemented a private CPython 3.13.12 bundle without PyInstaller, a passive
application-owned lazy supervisor, explicit operation startup, optional worker
prelaunch, and permanent shutdown fencing. Initial launches and automatic
recovery share startup synchronization. Per-instance pipes avoid cross-instance
connections. First downloads now enter the lazy worker rather than bypassing it.
New server-preload defaults are false; stored settings and optional preload are
preserved. The full add-on package builds and its extracted worker passes real
IPC, native-status, and checksum-verified download checks outside the checkout.

### P2: Model-management service is not the production authority

No production caller constructs `ModelManagementService` or invokes its
activation/reaper methods. Existing managers/catalog/settings remain the active
paths. The migration's centralized resource arbitration is therefore not active.

Wiring it directly would be unsafe: `request_activation()` commits accounting
before any load succeeds and ignores requested evictions; `reap_idle_models()`
only removes accounting, without runtime unload acknowledgement. Allocation
keys omit provider identity, and policies do not enforce descriptor RAM/VRAM
requirements or the advertised single-helper limit. These need a separate
resource-lifecycle design and end-to-end tests before activation.

## Verification

- Baseline: 783 Python tests passed, 2 skipped, 18 deselected; 60 subtests passed.
- Fixes were reproduced with failing tests before production changes.
- Final Python suite: 819 passed, 2 skipped, 18 deselected; 60 subtests passed.
- Python lint and focused regression tests pass.
- Rust supervisor: 20 tests passed with `PYO3_PYTHON` set to `.venv/Scripts/python.exe`.
  A first bare Cargo invocation selected host Python 3.14 and failed PyO3's
  supported-version check; using the project's Python 3.13 resolved it.
- SCons dry run and full package build pass, including the Web UI and native
  release builds. Recursive archive inspection found no tests or bytecode;
  extracted private-runtime checksums validate. Live NVDA startup/inference is
  not exercised by the standalone suite.
- Changed production-file whitespace checks pass. Whole-tree `git diff --check`
  additionally reports pre-existing trailing whitespace in
  `.agents/teamwork/sentinel/handoff.md`.
