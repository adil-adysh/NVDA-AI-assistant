# Project: NVDA AI Assistant — Migration Slice 0 & Slice 1

## Architecture
- **Native Runtime Supervisor (`runtime_supervisor`)**:
  - Authoritative native owner of local server processes (`litert-lm` and `llama-server`).
  - Monotonic generation counter fencing (`RS-01`) ensures status updates from prior epochs cannot corrupt newer states.
  - Strict `LifecycleState::Stopping` guard (`RS-02`) prevents race conditions between `ensure_ready` and `stop()`.
  - Deterministic process teardown and socket quiescence await (`RS-03`) prevents `WSAEADDRINUSE` port collisions.
  - Condvar wait on in-flight startup and bounded backoff (`RS-04`) prevents concurrent livelock.
  - Windows Win32 Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (`RS-06`) guarantees child process termination on crash.
  - Clean PyO3 module interface without production mock shims (`RS-10`).
- **Pure Python Domain & Service Layer**:
  - Standard library `logging.getLogger(__name__)` replaces NVDA `logHandler` across all pure domain/service modules.
  - Pluggable `register_language_resolver` port decouples `languageHandler` in `config/settings.py`.
  - Automated AST import boundary test (`tests/test_import_boundaries.py`) verifies zero forbidden NVDA imports across pure packages.
  - Ruff `TID251` banned API rules in `pyproject.toml` enforce boundaries at lint time.
- **Three-Tier Test Architecture**:
  - Root `conftest.py` conditionally initializes NVDA source only when `../nvda` is present; pure unit tests run standalone in < 3s without NVDA checkout.
  - Integration tests requiring real NVDA are marked with `pytestmark = pytest.mark.nvda_integration`.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | RS-01 Generation Counter Monotonicity | Increment `generation` on child exit, crash, and startup timeout in `supervisor.rs` | M1 | `architecture_deliverable.md §8.1`, `survey_explorer_rust_1` |
| 2 | RS-02 Stopping State Guard | Guard `ensure_ready` while `Stopping` and guard `stop()` state write with generation match | M1 | `architecture_deliverable.md §8.1`, `survey_explorer_rust_1` |
| 3 | RS-03 Restart Socket Quiescence | `restart()` awaits `proc.wait_timeout()` and verifies port quiescence before launching replacement | M1 | `architecture_deliverable.md §8.1`, `survey_explorer_rust_1` |
| 4 | RS-04 Startup Livelock Mitigation | Condvar wait on in-flight `Starting` with differing configs and bounded retry backoff | M1 | `architecture_deliverable.md §8.1`, `survey_explorer_rust_1` |
| 5 | RS-06 Windows Job Object Containment | Assign child process handles to Win32 Job Object with `KILL_ON_JOB_CLOSE` | M1 | `architecture_deliverable.md §8.1`, `survey_explorer_rust_1` |
| 6 | RS-10 PyO3 Interface Boundary Cleanliness | Verify zero test mock shims in PyO3 classes and confirm Python shims schedule | M1 | `architecture_deliverable.md §8.1`, `survey_explorer_rust_1` |
| 7 | RS Regression Test Suite | Implement 9 targeted regression tests in `runtime_supervisor/src/tests.rs` | M1 | `architecture_deliverable.md §18`, `survey_explorer_rust_1` |
| 8 | Conftest Sibling Decoupling | Add `HAS_NVDA_CHECKOUT` guard in root `conftest.py` and skip missing checkout tests in collection hook | M2 | `architecture_deliverable.md §7.2`, `survey_explorer_python_2` |
| 9 | Logging Facade & Bridge | Introduce `NVDALogBridge` in `utils/logger.py` and standardize pure modules to `logging.getLogger(__name__)` | M2 | `architecture_deliverable.md §6.1`, `survey_explorer_python_2` |
| 10 | Language Resolver Decoupling | Introduce `register_language_resolver` port in `config/settings.py`, eliminating `import languageHandler` | M2 | `architecture_deliverable.md §6.1`, `survey_explorer_python_2` |
| 11 | Pure Package Log Contamination Purge | Replace 17 `from logHandler import log` statements across pure domain/service packages | M2 | `architecture_deliverable.md §6.2`, `survey_explorer_python_2` |
| 12 | Automated AST Boundary Test | Implement `tests/test_import_boundaries.py` asserting zero forbidden NVDA imports in pure packages | M2 | `architecture_deliverable.md §6.3`, `survey_explorer_python_2` |
| 13 | Ruff Banned API Rules | Configure `tool.ruff.lint.flake8-tidy-imports.banned-api` with `TID251` and adapter exclusions | M2 | `architecture_deliverable.md §6.3`, `survey_explorer_python_2` |
| 14 | Integration Test Marking | Mark `tests/integration/test_nvda_imports.py` & `test_browser_field_parser.py` with `nvda_integration` | M2 | `architecture_deliverable.md §7.2`, `survey_explorer_python_2` |
| 15 | Standalone Pure Test Execution | Verify pure tests execute in < 3s with `uv run pytest -m "not nvda_integration"` without `../nvda` | M2 | `architecture_deliverable.md §7.2`, `survey_explorer_python_2` |
| 16 | Zero-Regression Verification Gate | Verify all 4 gates (`ruff check`, `cargo test`, `cargo check`, `pytest`) pass 100% | M3 | `ORIGINAL_REQUEST.md §R3`, `survey_explorer_baseline_3` |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Slice 0: Rust Runtime Supervisor Concurrency Hardening | Features 1–7 (RS-01..06, RS-10, `tests.rs` regression suite) | none | DONE |
| 2 | Slice 1: Pure Python Test Boundary Decoupling & Import Enforcement | Features 8–15 (conftest, logging facade, language port, AST boundary test, ruff TID251) | M1 | IN_PROGRESS |
| 3 | Integrated Zero-Regression Verification Gate | Feature 16 (Full build/lint/test pass across Python and Rust, victory forensic audit) | M1, M2 | PLANNED |

## Interface Contracts
### Native `RuntimeSupervisor` ↔ Python Runtime Manager
- `RuntimeStatus`: `state: str`, `pid: int | None`, `port: int`, `generation: int`, `last_error: str | None`.
- `ensure_ready(config_json: str, timeout_secs: float) -> RuntimeStatus`:
  - Returns `ReadyOwned` or `ReadyAdopted`.
  - Rejects or waits during `Stopping` and `Restarting` until process fully terminates.
  - Thread-safe: concurrent calls with identical config wait and return; differing config waits for in-flight startup before reconciling.
  - Spawns child process inside Win32 Job Object (`KILL_ON_JOB_CLOSE`).
- `stop(timeout_secs: float) -> RuntimeStatus`:
  - Increments generation, sets `Stopping`, terminates process, awaits exit, sets `Stopped` only if generation unchanged.
- `restart(config_json: str, timeout_secs: float) -> RuntimeStatus`:
  - Waits for process exit and port release before re-spawning.

### Pure Domain Logging ↔ NVDA Logging
- Pure modules use standard library `logging.getLogger(__name__)`.
- Adapter layer attaches `NVDALogBridge(logging.Handler)` targeting `logHandler.log`.
- `config/settings.py` provides `register_language_resolver(resolver: Callable[[], str]) -> None` with default fallback to `"en"`.

## Code Layout
- `runtime_supervisor/`:
  - `src/supervisor.rs`: State machine, generation counter, condvar coordination, `ensure_ready`, `stop`, `restart`.
  - `src/process.rs`: `ProcessDriver`, child process spawning, Win32 Job Object containment.
  - `src/health.rs`: HTTP health checks, port polling.
  - `src/tests.rs`: Unit and integration regression tests (20 tests).
  - `Cargo.toml`: Rust crate manifest.
- `addon/globalPlugins/AI-assistant/`:
  - `utils/logger.py`: Logging facade & `NVDALogBridge`.
  - `config/settings.py`: Language resolver port.
  - Pure domain packages (`core/`, `config/`, `service/`, `providers/`, `use_case/`, `prompts/`, `tools/`, `observability/`, `embeddings/`): Zero forbidden NVDA imports.
- `tests/`:
  - `conftest.py`: Decoupled universal root conftest.
  - `test_import_boundaries.py`: AST-based import boundary enforcement test.
  - `integration/`: Marked with `pytest.mark.nvda_integration`.
