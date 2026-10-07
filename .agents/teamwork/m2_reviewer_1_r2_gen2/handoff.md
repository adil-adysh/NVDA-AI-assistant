# Milestone 2 Review & Adversarial Challenge Report (Iteration 2)

**Role**: Milestone 2 Reviewer & Adversarial Critic (`m2_reviewer_1_r2_gen2`)  
**Date**: 2026-10-04T23:17:00Z  
**Type**: Hard Handoff (Task Complete)  
**Parent Agent ID**: `7cada731-7b2c-48e6-9591-543160b4eac8`  
**Verdict**: **APPROVE**

---

## 1. Observation

Direct observations from source inspection, git diffs, empirical execution, and adversarial stress tests:

1. **Root `conftest.py` Decoupling & Fallback Shims**:
   - `conftest.py:27`: Defines `HAS_NVDA_CHECKOUT = not os.environ.get("NVDA_STANDALONE") and (NVDA_SOURCE / "api.py").is_file()`.
   - `conftest.py:39-95`: All real NVDA imports (`globalVars`, `controlTypes`, `logHandler`, `textInfos`) and `sys.path` modifications are strictly gated within `if HAS_NVDA_CHECKOUT:`.
   - `conftest.py:96-104`: Provides a standard library fallback shim for `logHandler` when sibling checkout is absent:
     ```python
     if not HAS_NVDA_CHECKOUT:
         if "logHandler" not in sys.modules:
             import logging
             import types

             log_module = types.ModuleType("logHandler")
             log_module.log = logging.getLogger("nvda.fallback")
             log_module.logHandler = None
             sys.modules["logHandler"] = log_module
     ```
   - `conftest.py:107-116`: `pytest_collection_modifyitems` attaches `pytest.mark.skip(reason="Sibling NVDA checkout not found at ../nvda. Pure tests pass without it.")` to all items containing the `nvda_integration` keyword when `not HAS_NVDA_CHECKOUT`.

2. **Integration Test Marking & Navigation Gating**:
   - `tests/context/test_navigation.py:109`: `NavigationTests.test_resolution_uses_duplicate_occurrence` decorated with `@pytest.mark.nvda_integration`.
   - `tests/context/extractors/test_browser_field_parser.py:10`: `pytestmark = pytest.mark.nvda_integration`.
   - `tests/context/test_browser_field_graph.py:13`: `pytestmark = pytest.mark.nvda_integration`.
   - `tests/integration/test_nvda_imports.py:11`: `pytestmark = pytest.mark.nvda_integration`.
   - `tests/integration/test_nvda_runtime.py:17`: `pytestmark = pytest.mark.nvda_integration`.
   - `tests/context/navigation.py:634-637`: `resolve_and_move_target` imports `textInfos` at runtime; when absent, it gracefully returns `(False, "NVDA browser navigation is unavailable.")`.

3. **Pure Module Decoupling and Lazy Exports**:
   - `addon/globalPlugins/AI-assistant/utils/__init__.py:14-20`: Eager import `from .clipboard import safe_read_clipboard` replaced with PEP 562 `__getattr__(name)`.
   - `addon/globalPlugins/AI-assistant/utils/clipboard.py:11-13`: Replaced `from logHandler import log` with `import logging; log = logging.getLogger(__name__)`.
   - `addon/globalPlugins/AI-assistant/plugin/presenter.py:7,54`, `background.py:8,37`, `ui/adapter.py:8,24`, `ui/task_runner.py:16,21`: Replaced `from logHandler import log` with `import logging; log = logging.getLogger(__name__)`.
   - All 17 `from logHandler import log` statements in pure packages (`core/`, `config/`, `service/`, `providers/`, `use_case/`, `prompts/`, `tools/`, `observability/`, `embeddings/`) have been removed; grep across these trees confirms 0 matches.

4. **Production Wiring of Logging Bridge and Language Resolver**:
   - `addon/globalPlugins/AI-assistant/plugin/application.py:62-71`: `AIAssistantApplication.__init__` explicitly calls `attach_nvda_log_bridge()` and registers `register_language_resolver(languageHandler.getLanguage)`.
   - `addon/globalPlugins/AI-assistant/plugin/application.py:184-189`: `AIAssistantApplication.terminate` safely resets `register_language_resolver(None)`.
   - `addon/globalPlugins/AI-assistant/config/settings.py:206-220`: `get_effective_language()` falls back cleanly to `"en"` if `_language_resolver` is `None` or raises an exception.
   - `addon/globalPlugins/AI-assistant/utils/logger.py:78-79`: `target_logger.setLevel(logging.DEBUG)` ensures all levels pass through the bridge.

5. **AST Boundary Scanner & Static Linting**:
   - `tests/test_import_boundaries.py`: Checks 110 files across pure packages, context modules, and utility modules (`crypto.py`, `markdown.py`, `mathml.py`).
   - `tests/test_import_boundaries.py:211-248`: Performance test verifies the entire AST scan finishes well under the 150ms budget (empirically ~60ms).
   - `pyproject.toml:90-109`: Configured `TID251` for 18 forbidden NVDA/host modules with per-file exceptions strictly bounded to Layer 0 adapter files.

6. **Empirical Command Verifications**:
   - `uv run pytest -m "not nvda_integration"`: `450 passed, 18 deselected in 13.38s` (Exit Code: 0).
   - Simulated absent checkout (`Path.is_file` returns False for `api.py`): `450 passed, 18 deselected in 13.41s` (Exit Code: 0).
   - `uv run pytest`: `450 passed, 18 deselected in 13.44s` (Exit Code: 0).
   - `uv run ruff check .`: `All checks passed!` (Exit Code: 0).
   - `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml`: `20 passed; 0 failed in 1.55s` (Exit Code: 0).
   - `cargo check --manifest-path nvda_ui_host/Cargo.toml`: Finished dev profile in 0.03s (Exit Code: 0).
   - Standalone execution with `NVDA_STANDALONE=1`: `450 passed, 18 deselected in 13.36s` (Exit Code: 0).
   - Explicit `nvda_integration` test run under `NVDA_STANDALONE=1`: `18 skipped, 450 deselected in 0.52s` (Exit Code: 0).
   - Pure isolated load test `load_addon_module('config.yaml_store', namespace='pure_test')`: Succeeded with code 0.

---

## 2. Logic Chain

1. **Decoupling Integrity**:
   - The original issue was test collection failure outside the sibling NVDA tree due to eager imports of `logHandler` through `utils/__init__.py -> clipboard.py` and direct `from logHandler import log` in presenter/background/adapter/task_runner.
   - By eliminating eager clipboard re-exporting in `utils/__init__.py` (converting to PEP 562 dynamic `__getattr__`) and replacing `from logHandler import log` with standard `logging.getLogger(__name__)` across all pure and boundary modules, pure modules no longer require `logHandler` to import.
   - The addition of `HAS_NVDA_CHECKOUT` and the fallback `logHandler` shim in `conftest.py` ensures that even if an indirect reference occurs, pytest collection does not abort.
   - Therefore, running tests with absent sibling checkout collects cleanly without errors.

2. **Test Tier Separation**:
   - Document navigation candidate resolution in `tests/context/test_navigation.py` specifically tests live document navigation requiring `textInfos.POSITION_FIRST`.
   - Applying `@pytest.mark.nvda_integration` to `test_resolution_uses_duplicate_occurrence` accurately reflects its dependency on live NVDA document constants.
   - In `conftest.py`, `pytest_collection_modifyitems` marks all 18 `nvda_integration` tests as skipped when `HAS_NVDA_CHECKOUT` is False.
   - Default pytest options in `pyproject.toml` (`-m "not nvda_integration"`) deselect these 18 tests during standalone runs, leaving exactly 450 pure tests that execute in ~13s.
   - When explicitly requesting `-m nvda_integration` under standalone mode, `pytest_collection_modifyitems` intercepts the items and skips all 18 tests with code 0 in 0.52s.
   - Therefore, the three-tier test architecture is fully operational and decoupled.

3. **Integrity & Facade Verification**:
   - The review explicitly probed whether `attach_nvda_log_bridge()` or `register_language_resolver()` were facades or dead code.
   - Direct inspection of `addon/globalPlugins/AI-assistant/plugin/application.py` shows genuine wiring: `attach_nvda_log_bridge()` and `register_language_resolver(languageHandler.getLanguage)` are invoked in `__init__`, and `register_language_resolver(None)` is invoked during `terminate()`.
   - `NVDALogBridge.emit()` actively inspects `record._nvda_bridged`, computes caller `codepath`, and dispatches to `nvda_log._log()`.
   - Stress-testing the AST scanner with synthetic violations proved it actively detects forbidden imports (both direct and dynamic/relative imports) and is not a facade.
   - Therefore, no integrity violations, facade implementations, or hardcoded shortcuts exist.

---

## 3. Caveats

- **Full NVDA Integration Tier**: Testing tests marked with `pytest.mark.nvda_integration` against live NVDA definitions requires the sibling `../nvda` checkout to be present and built with compiled helper DLLs (`nvdaHelperLocal.dll`). When running standalone or in CI without the sibling repo, these 18 tests are skipped by design.
- **`safe_read_clipboard` Outside NVDA**: When `safe_read_clipboard()` is called outside of NVDA, `import api` fails, which triggers `log.exception("Error reading clipboard via api.getClipData")` and returns `None`. In standalone pure tests, clipboard functions are not called unless specifically unit-tested, but an unhandled logger would emit an exception traceback to stderr. This is benign as it returns `None` safely.

---

## 4. Conclusion

The implementation fully satisfies all requirements of Slice 0 and Slice 1:
- Root `conftest.py` is cleanly decoupled from `../nvda`.
- Pure Python tests collect and pass 100% (450 passed) in standalone mode with absent sibling checkout.
- Automated AST boundary scanner and Ruff `TID251` rules are active, watertight, and validated.
- Zero integrity violations, zero regressions, and all quality gates pass.

**Verdict**: **APPROVE**

---

## 5. Verification Method

To independently verify the review conclusions, execute the following commands from the repository root:

1. **Verify Pure Test Suite Standalone**:
   ```pwsh
   uv run pytest -m "not nvda_integration"
   ```
   *Expected Output*: `450 passed, 18 deselected in ~13s` (Exit code: 0).

2. **Verify Simulated Absent Sibling Checkout**:
   ```pwsh
   uv run python -c "import pathlib, os, pytest; orig = pathlib.Path.is_file; pathlib.Path.is_file = lambda s: False if 'api.py' in str(s) else orig(s); raise SystemExit(pytest.main(['-m', 'not nvda_integration']))"
   ```
   *Expected Output*: `450 passed, 18 deselected in ~13s` (Exit code: 0).

3. **Verify Full Default Pytest Suite**:
   ```pwsh
   uv run pytest
   ```
   *Expected Output*: `450 passed, 18 deselected in ~13s` (Exit code: 0).

4. **Verify Clean Skip Behavior on Explicit Integration Selection without NVDA**:
   ```pwsh
   uv run python -c "import os, pytest; os.environ['NVDA_STANDALONE']='1'; raise SystemExit(pytest.main(['-m', 'nvda_integration']))"
   ```
   *Expected Output*: `18 skipped, 450 deselected in <1s` (Exit code: 0).

5. **Verify AST Architecture Enforcement & Static Lint**:
   ```pwsh
   uv run pytest tests/test_import_boundaries.py
   uv run ruff check .
   ```
   *Expected Output*: 4 tests passed in ~0.15s; 0 lint errors (Exit code: 0).

6. **Verify Rust Supervisors**:
   ```pwsh
   uv run cargo test --manifest-path runtime_supervisor/Cargo.toml
   cargo check --manifest-path nvda_ui_host/Cargo.toml
   ```
   *Expected Output*: 20 passed, 0 failed; finished dev profile in <0.1s (Exit code: 0).

---

## Adversarial Challenge & Stress-Test Report

### Overall Risk Assessment: LOW

### Stress Tests Executed

1. **Absent Sibling Tree Simulation (`api.py` missing)**:
   - *Scenario*: Monkeypatch `Path.is_file` to return `False` for `api.py`.
   - *Result*: Clean collection and execution. 450 pure tests passed, 18 integration tests deselected. 0 collection crashes. **PASS**.
2. **Explicit Integration Test Request in Standalone Mode (`NVDA_STANDALONE=1`)**:
   - *Scenario*: Invoke `pytest.main(['-m', 'nvda_integration'])` with `NVDA_STANDALONE=1`.
   - *Result*: `18 skipped, 450 deselected in 0.52s`. Every marked integration test received a `skip` marker from `pytest_collection_modifyitems` with explicit reason. **PASS**.
3. **AST Boundary Scanner Detection Sensitivity**:
   - *Scenario*: Injected synthetic forbidden statements (`import api`, `from speech import ...`, `from . import api`, `__import__("logHandler")`).
   - *Result*: Scanner successfully caught every forbidden direct, relative, and dynamic import pattern. **PASS**.
4. **Pure Module Isolation (`config.yaml_store`)**:
   - *Scenario*: Loaded `config.yaml_store` in isolated test namespace via `load_addon_module`.
   - *Result*: Module loaded cleanly without invoking NVDA runtime or crashing on `logHandler`. **PASS**.
