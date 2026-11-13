# Worker isolation implementation plan

**Goal:** Keep NVDA responsive and isolate native model execution behind the packaged worker.

**Architecture:** Runtime and embedding calls become correlated jobs. Submission, health,
cancellation and shutdown remain short command transactions; progress and terminal results
use the event pipe. NVDA owns settings, context snapshots, chat policy and presentation.

**Approved scope:** User approved all recommendations in the worker audit on 2026-10-12.
**Execution:** Inline in the current checkout; preserve the current branch and existing work.

## Tasks
- [x] Extract runtime command dispatch into `worker/runtime_commands.py`; add
  `runtime_command` jobs with per-runtime serialization and responsive stop dispatch.
- [x] Add a job-backed runtime bridge to `service/worker_client.py`, bounded control
  transactions, request cancellation, generation checks, terminal cleanup and disconnect handling.
- [x] Keep terminal events reliable under progress congestion; reject duplicate jobs.
- [x] Remove NVDA runtime execution fallbacks and native runtime imports; force upgrade
  verification through the worker. Keep explicit test-injected supervisor ports only.
- [x] Add worker embedding execution and replace NVDA engine construction with worker ports.
  Cover inference, model discovery, preparation, cache inspection and deletion.
- [x] Audit persistence/image paths; move chat repository access away from the NVDA
  event thread while preserving snapshot affinity and presentation delivery.
- [x] Verify slow-job cancellation/health/shutdown, stale generations, crash release,
  independent jobs, model policies, embeddings and packaging. Run Ruff, pytest,
  native supervisor tests, host/web checks and SCons sequentially.

## Failure expectations
- A long operation must not hold the command lock or listener.
- Cancellation before execution causes no model mutation; CLI cancellation terminates
  its child; native inference results are discarded after cancellation.
- Runtime stop remains available with all ordinary execution slots occupied.
- A disconnected worker releases every pending waiter exactly once.
- Old-generation events never complete or update a new-generation job.
- No provider operations, filesystem hashing or native embedding loading run on the
  NVDA event thread; accessibility capture remains there.

## Completed verification

- Ruff and whitespace checks passed.
- Full suite with required packaged/LiteRT artifacts: 960 passed, 2 skipped,
  18 NVDA integration tests deselected, 60 subtests passed.
- Built-NVDA integration tier: all 18 tests passed after isolating collection and
  regenerating stale sibling NVDA COM interface build artifacts.
- Native supervisor: 23 tests passed; host cargo check passed.
- Embedding and memory extensions compile and build; the packaged worker imports
  them and uses the native conversation database in an isolated data directory.
- Full SCons package build and Web UI build passed.
- The actual packaged worker starts LiteRT-LM 0.18.0, serves `/v1/models`, and stops it.
- Independent review findings on writes, batches, scheduling and startup races
  were fixed and regression-tested; no remaining P1/P2 findings reported.

## Audit decisions

Image resize/encoding already runs after the event-thread accessibility capture;
that boundary is preserved. Conversation native/database IO moved into the worker.
Native embedding cancellation discards results and yields between minibatches;
an individual native load/inference call can finish before yielding. Production
managed runtime work uses the worker; explicit injected native supervisor ports
remain for focused tests and legacy synchronous worker RPC remains for old clients.

Integration collection previously imported standalone test modules before
marker deselection. A test logger replacement hid real NVDA API definitions,
and GUI stubs polluted inspection. The integration-only collection now discovers
all files declaring the integration marker without importing unrelated unit-test
modules. The standalone logger test retains an existing real `logHandler` module.
