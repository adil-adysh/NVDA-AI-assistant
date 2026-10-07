# Adversarial Review Handoff Report: Sibling NVDA Decoupling & Test Tier Gating

**VERDICT**: **REQUEST_CHANGES**

---

## 1. Observation

### Obs 1: Standard Pure Test Run Relies on Existing Sibling NVDA Checkout
Command executed:
```powershell
uv run pytest -m "not nvda_integration"
```
Output:
```
collected 467 items / 17 deselected / 450 selected
===================== 450 passed, 17 deselected in 13.20s =====================
```
In `conftest.py` line 27:
```python
HAS_NVDA_CHECKOUT = (NVDA_SOURCE / "api.py").is_file()
```
Because the pinned sibling checkout exists at `D:\nvda-addons\nvda\source\api.py`, `HAS_NVDA_CHECKOUT` evaluates to `True`. As a result, lines 61-94 of `conftest.py` execute unconditionally:
```python
	for path in reversed((NVDA_SOURCE, NVDA_MISC_DEPS)):
		path_string = str(path)
		if path_string not in sys.path:
			sys.path.insert(0, path_string)
...
	import controlTypes
	import logHandler
	import textInfos
```
Thus, the 450 tests passed with `../nvda/source` present in `sys.path` and real NVDA modules loaded into `sys.modules`.

### Obs 2: Adversarial Simulation of Absent Sibling NVDA Checkout Causes Pytest Collection Crash
Command executed:
```powershell
uv run python -c "from pathlib import Path; orig = Path.is_file; Path.is_file = lambda s: False if 'api.py' in str(s) else orig(s); import pytest, sys; sys.exit(pytest.main(['-m', 'not nvda_integration']))"
```
Output:
```
Traceback:
tests\architecture\test_use_case_flow.py:10: in <module>
    from tests.plugin import test_presenter_ui_actions as presenter_harness
tests\plugin\test_presenter_ui_actions.py:266: in <module>
    presenter_module = _load_module(f"{PACKAGE_NAME}.plugin.presenter", MODULE_DIR / "presenter.py")
tests\support\bootstrap.py:45: in load_module
    spec.loader.exec_module(module)
addon\globalPlugins\AI-assistant\plugin\presenter.py:9: in <module>
    from logHandler import log
E   ModuleNotFoundError: No module named 'logHandler'
...
=========================== short test summary info ===========================
ERROR tests/architecture/test_use_case_flow.py
ERROR tests/config/test_yaml_store.py
ERROR tests/integration/test_chat_lifecycle.py
ERROR tests/plugin/test_background_provider_ready.py
ERROR tests/plugin/test_background_shutdown.py
ERROR tests/plugin/test_presenter_ui_actions.py
ERROR tests/providers/test_llama_provider.py
ERROR tests/ui/test_adapter_fallback.py
!!!!!!!!!!!!!!!!!!! Interrupted: 8 errors during collection !!!!!!!!!!!!!!!!!!!
====================== 17 deselected, 8 errors in 0.55s =======================
```

### Obs 3: Full Run with `--continue-on-collection-errors` Reveals 8 Collection Errors and 4 Test Failures
Command executed:
```powershell
uv run python -c "from pathlib import Path; orig = Path.is_file; Path.is_file = lambda s: False if 'api.py' in str(s) else orig(s); import pytest, sys; sys.exit(pytest.main(['-m', 'not nvda_integration', '--continue-on-collection-errors']))"
```
Output:
```
FAILED tests/context/test_navigation.py::NavigationTests::test_resolution_uses_duplicate_occurrence
FAILED tests/ui/test_task_runner.py::BackgroundTaskRunnerTests::test_destroyed_owner_does_not_receive_callback
FAILED tests/ui/test_task_runner.py::BackgroundTaskRunnerTests::test_failure_without_handler_is_reported
FAILED tests/ui/test_task_runner.py::BackgroundTaskRunnerTests::test_success_is_dispatched_and_work_runs_off_main_thread
ERROR tests/architecture/test_use_case_flow.py
ERROR tests/config/test_yaml_store.py
ERROR tests/integration/test_chat_lifecycle.py
ERROR tests/plugin/test_background_provider_ready.py
ERROR tests/plugin/test_background_shutdown.py
ERROR tests/plugin/test_presenter_ui_actions.py
ERROR tests/providers/test_llama_provider.py
ERROR tests/ui/test_adapter_fallback.py
=========== 4 failed, 398 passed, 17 deselected, 8 errors in 12.90s ===========
```

### Obs 4: Contamination Path in `utils/clipboard.py` and `utils/__init__.py`
In `addon/globalPlugins/AI-assistant/utils/clipboard.py`:
- Line 11: `from logHandler import log`
- Line 21: `import api` inside `safe_read_clipboard()`

In `addon/globalPlugins/AI-assistant/utils/__init__.py`:
- Line 4: `from .clipboard import safe_read_clipboard`

In `addon/globalPlugins/AI-assistant/config/yaml_store.py`:
- Line 12: `from ..utils.crypto import decrypt_value, encrypt_value, is_encrypted, is_sensitive_key`

When any module imports from `utils` (e.g. `config.yaml_store` importing `..utils.crypto`), Python loads package `utils` by executing `addon/globalPlugins/AI-assistant/utils/__init__.py`, which eagerly executes `utils/clipboard.py`, triggering `from logHandler import log`.

### Obs 5: `tests/test_import_boundaries.py` Omitted `utils`
In `tests/test_import_boundaries.py` lines 15-25:
```python
PURE_DIRECTORIES: tuple[str, ...] = (
	"core",
	"config",
	"service",
	"providers",
	"use_case",
	"prompts",
	"tools",
	"observability",
	"embeddings",
)
```
`"utils"` is not included in `PURE_DIRECTORIES`. Thus, `test_pure_packages_have_zero_forbidden_nvda_imports()` passes despite `utils/clipboard.py` containing forbidden `logHandler` and `api` imports.

### Obs 6: Per-File Isolation Test Identifies 10 Non-Integration Test Files Failing Standalone
When running every test file individually under simulated absent NVDA checkout (`Path.is_file` returning False for `api.py`):
Total files tested: 60.
Total failed in isolation: 15.
- 4 files are correctly marked `nvda_integration` and deselected (0 tests run).
- 1 file (`tests/ui/test_bootstrap.py`) contains 0 tests.
- 10 unmarked files (classified as pure) failed:
  1. `tests/architecture/test_use_case_flow.py` (Collection Error: `logHandler`)
  2. `tests/config/test_yaml_store.py` (Collection Error: `logHandler` via `utils/__init__.py`)
  3. `tests/integration/test_chat_lifecycle.py` (Collection Error: `logHandler` via `utils/__init__.py`)
  4. `tests/plugin/test_background_provider_ready.py` (Collection Error: `logHandler` via `plugin/background.py`)
  5. `tests/plugin/test_background_shutdown.py` (Collection Error: `logHandler` via `plugin/background.py`)
  6. `tests/plugin/test_presenter_ui_actions.py` (Collection Error: `logHandler` via `plugin/presenter.py`)
  7. `tests/providers/test_llama_provider.py` (Collection Error: `logHandler` via `utils/__init__.py`)
  8. `tests/ui/test_adapter_fallback.py` (Collection Error: `logHandler` via `ui/adapter.py`)
  9. `tests/ui/test_task_runner.py` (Test Failure: `logHandler` via `ui/task_runner.py`)
  10. `tests/context/test_navigation.py` (Test Failure: `AssertionError: False is not true` in `NavigationTests.test_resolution_uses_duplicate_occurrence` because `resolve_and_move_target` in `context/navigation.py:635` fails `import textInfos`)

---

## 2. Logic Chain

1. **Premise**: The acceptance criteria in `ORIGINAL_REQUEST.md §R2` and `PROJECT.md Feature 15` state:
   *"uv run pytest -m 'not nvda_integration' succeeds even if ../nvda is absent or uninitialized."*
2. **Finding 1**: When `../nvda` checkout is absent, `conftest.py` skips inserting `NVDA_SOURCE` into `sys.path`.
3. **Finding 2**: In that absent state, `uv run pytest -m 'not nvda_integration'` crashes immediately with 8 collection errors and 4 test failures (Obs 2 & Obs 3).
4. **Finding 3**: Three pure/service tests (`test_yaml_store.py`, `test_chat_lifecycle.py`, `test_llama_provider.py`) fail solely because `addon/globalPlugins/AI-assistant/utils/clipboard.py` still contains `from logHandler import log` and `import api`, and `utils/__init__.py` eagerly exports `safe_read_clipboard` (Obs 4).
5. **Finding 4**: `tests/test_import_boundaries.py` failed to catch this defect because `utils` was omitted from `PURE_DIRECTORIES` (Obs 5).
6. **Finding 5**: Six UI/plugin tests (`test_presenter_ui_actions.py`, `test_background_provider_ready.py`, `test_background_shutdown.py`, `test_adapter_fallback.py`, `test_task_runner.py`, `test_use_case_flow.py`) load modules that import `logHandler` directly, but are not marked with `pytestmark = pytest.mark.nvda_integration` nor decoupled (Obs 6).
7. **Finding 6**: `tests/context/test_navigation.py` contains a test `test_resolution_uses_duplicate_occurrence` that relies on real NVDA `textInfos` without being marked as `nvda_integration` (Obs 6).
8. **Conclusion**: The requirement that pure tests run cleanly without the sibling `../nvda` checkout is NOT satisfied. Changes are required to achieve true decoupling.

---

## 3. Caveats

- Rust test suite `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml` and Rust build `cargo check --manifest-path nvda_ui_host/Cargo.toml` passed 100% (20 tests passed). Slice 0 native supervisor hardening is solid.
- Code style and linting `uv run ruff check .` passed with 0 errors.
- The failure only manifests when the sibling NVDA checkout is absent or simulated absent, which is why existing test runs that execute in environments with `../nvda` appeared to pass.

---

## 4. Conclusion & Required Changes

The assertion that pure tests do not require the sibling `../nvda` checkout is empirically disproven.

### Required Actions (REQUEST_CHANGES):
1. **Decouple `utils/clipboard.py`**:
   - Replace `from logHandler import log` with `logging.getLogger(__name__)`.
   - Prevent eager import of `clipboard.py` in `utils/__init__.py` or isolate it so importing `utils.crypto` never imports NVDA modules.
2. **Add `utils` to `tests/test_import_boundaries.py`**:
   - Add `"utils"` to `PURE_DIRECTORIES` in `tests/test_import_boundaries.py`.
3. **Decouple or Gate `tests/context/test_navigation.py`**:
   - In `tests/context/test_navigation.py`, stub `textInfos.POSITION_FIRST` in `NavigationTests.test_resolution_uses_duplicate_occurrence` or mark the test with `@pytest.mark.nvda_integration`.
4. **Mark or Decouple Plugin and UI Tests**:
   - Mark `tests/ui/test_adapter_fallback.py`, `tests/ui/test_task_runner.py`, `tests/plugin/test_presenter_ui_actions.py`, `tests/plugin/test_background_provider_ready.py`, `tests/plugin/test_background_shutdown.py`, and `tests/architecture/test_use_case_flow.py` with `pytestmark = pytest.mark.nvda_integration`, OR decouple their logging by installing a fallback `logHandler` logging bridge in `conftest.py` when `not HAS_NVDA_CHECKOUT`.
5. **Support CI Standalone Simulation in `conftest.py`**:
   - Update `conftest.py` line 27 so that `HAS_NVDA_CHECKOUT = (NVDA_SOURCE / "api.py").is_file() and not os.environ.get("NVDA_STANDALONE")`. This enables deterministic standalone validation in any environment.

---

## 5. Verification Method

To independently verify the failure and the fix:

```powershell
# 1. Run pure test tier with simulated absent NVDA checkout
uv run python -c "from pathlib import Path; orig = Path.is_file; Path.is_file = lambda s: False if 'api.py' in str(s) else orig(s); import pytest, sys; sys.exit(pytest.main(['-m', 'not nvda_integration']))"

# Invalidation Condition:
# The fix is validated when this command exits with code 0 and 0 collection errors/failures.
```
