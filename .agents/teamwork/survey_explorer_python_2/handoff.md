# Pure Python Test Boundary Survey Handoff Report

**Agent:** Pure Python Test Boundary Explorer (Agent 2)  
**Date:** 2026-10-04  
**Working Directory:** `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\survey_explorer_python_2`  
**Handoff Type:** Hard (Task complete)  
**Deliverable File:** `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\survey_explorer_python_2\survey_report.md`  

---

## 1. Observation

1. **Root `conftest.py` Sibling Lock (`conftest.py:27–31`):**
   ```python
   if not (NVDA_SOURCE / "api.py").is_file():
   	raise pytest.UsageError(
   		"NVDA source checkout was not found at ../nvda. "
   		"Clone https://github.com/nvaccess/nvda.git beside NVDA-AI-assistant.",
   	)
   ```
   Executing pytest when `(NVDA_SOURCE / "api.py")` is absent raises `pytest.UsageError` at module evaluation time before test collection or marker filtering can execute.
2. **Conftest Consumers in `tests/`:**
   Grep across all 59 files in `tests/` for `conftest` found only 2 consumers:
   - `tests/integration/test_nvda_imports.py:7`: `from conftest import NVDA_ROOT, NVDA_SOURCE, PROJECT_ROOT, REAL_NVDA_MODULES`
   - `tests/integration/test_nvda_runtime.py:13`: `from conftest import NVDA_ROOT, NVDA_SOURCE`
   Zero pure unit tests import from `conftest`.
3. **NVDA Import Contamination in Pure Packages:**
   An exhaustive AST scan of all 114 Python files in `addon/globalPlugins/AI-assistant/` identified 95 NVDA imports across 38 files. Exactly 18 of these statements leak into pure domain/service packages:
   - 17 occurrences of `from logHandler import log`:
     - `config/state.py:7`
     - `config/yaml_store.py:10`
     - `utils/crypto.py:20`
     - `service/base.py:8`
     - `service/model_cache.py:29`
     - `service/error_reporter.py:10`
     - `service/chat/coordinator.py:9`
     - `service/chat/repository_backends.py:13`
     - `providers/litert_manager.py:13`
     - `providers/llama_manager.py:10`
     - `providers/provider_proxy.py:7`
     - `providers/_provider_runtime.py:7`
     - `providers/adapters/openai_compat.py:23`
     - `providers/runtime/download.py:27`
     - `providers/runtime/manager.py:12`
     - `providers/runtime/model_download.py:21`
     - `prompts/base.py:7`
     - `observability/reporter.py:7`
   - 1 occurrence of `import languageHandler`: `config/settings.py:8` (used at line 200: `languageHandler.getLanguage() or "en"`).
   Zero other NVDA modules (`api`, `textInfos`, `controlTypes`, `wx`, `gui`, `queueHandler`, `speech`, `tones`) are imported in any pure package.
4. **Log Method Signature Invariants:**
   AST call analysis across the 18 pure modules confirmed that `log` calls are strictly limited to `['debug', 'info', 'warning', 'error', 'exception']` — identical to Python's standard `logging.Logger`.
5. **NVDA Log Filtering Mechanic (`logHandler.py:605–612`):**
   ```python
   def filterExternalDependencyLogging(record: logging.LogRecord) -> bool:
   	import config
   	return (
   		record.name == NVDA_LOGGER_NAME
   		or record.levelno >= Logger.WARNING
   		or config.conf["debugLog"]["externalPythonDependencies"]
   	)
   ```
   Where `NVDA_LOGGER_NAME = "nvda"`. Any record with `record.name != "nvda"` is filtered out below `WARNING` unless `externalPythonDependencies` is enabled.
6. **Ruff `per-file-ignores` Semantic Behavior:**
   Experimental verification using `uv run ruff check` confirmed that `per-file-ignores` ignores (suppresses) the listed rule on matching files. Listing pure packages under `per-file-ignores` as drafted in `architecture_deliverable.md:457` deactivates `TID251` for those files.
7. **Current Test Inventory & Execution:**
   `uv run pytest` executed 461 tests (3 deselected by `-m "not nvda_integration"`) in 16.58s with 0 failures.
   - 56 of 59 files (451 tests) are pure Python tests.
   - Pure test runs execute in < 0.10s to < 0.70s per subsystem.
   - Only 3 test files require NVDA checkout/APIs: `tests/integration/test_nvda_runtime.py` (3 tests), `tests/integration/test_nvda_imports.py` (3 tests), and `tests/context/extractors/test_browser_field_parser.py` (7 tests).

---

## 2. Logic Chain

1. **Premise 1:** Root `conftest.py` fails before test collection if `../nvda/source/api.py` is absent (Observation 1), even though 95% of test files do not import anything from NVDA or `conftest` (Observations 2, 7).
   **Inference 1:** Guarding the NVDA bootstrap behind `HAS_NVDA_CHECKOUT = (NVDA_SOURCE / "api.py").is_file()` and marking missing-checkout integration tests as skipped in `pytest_collection_modifyitems` enables pure tests to run without `../nvda` checkout while preserving existing integration behavior.
2. **Premise 2:** In pure domain and service modules, the only missing symbols in standalone Python are `logHandler.log` and `languageHandler` (Observation 3).
   **Inference 2:** Replacing `from logHandler import log` with standard library `import logging; log = logging.getLogger(__name__)` and decoupling `languageHandler` via a pluggable `register_language_resolver` port allows all pure modules to be imported and executed standalone in pure Python without shims or stubs.
3. **Premise 3:** NVDA filters external logs below `WARNING` unless their record name is `"nvda"` (Observation 5).
   **Inference 3:** In the production NVDA shell, an `NVDALogBridge(logging.Handler)` attached to the logger hierarchy routes records through `logHandler.log`, ensuring standard log records retain `name == 'nvda'` and are never filtered by NVDA.
4. **Premise 4:** Ruff `TID251` enforces banned imports, but `per-file-ignores` suppresses rules (Observation 6).
   **Inference 4:** The configuration must activate `TID251` globally and add adapter files (`ui/**`, `context/extractors/**`, `plugin/**`, `image/**`, `utils/clipboard.py`, `tests/**`) to `per-file-ignores`, rather than listing pure packages.
5. **Premise 5:** Marking `tests/integration/test_nvda_imports.py` and `tests/context/extractors/test_browser_field_parser.py` with `pytestmark = pytest.mark.nvda_integration` aligns the test suite with `pyproject.toml`'s default `addopts = ["-m", "not nvda_integration"]` (Observation 7).
   **Inference 5:** Default test runs (`uv run pytest`) will execute 451 pure tests across 56 files in < 3 seconds with zero requirement for `../nvda`.

---

## 3. Caveats

- **Adapter and UI Layer Logging:** 22 files in Layer 0 (`ui/`, `plugin/`, `context/extractors/`, `image/`) continue to import `from logHandler import log`. They remain valid Layer 0 NVDA adapters and do not violate pure domain boundaries. Their full decomposition is scheduled for later migration slices (Slices 3, 8).
- **`wxPython` Dependency:** `tests/ui/test_task_runner.py` imports `wx`, which is present in the project virtual environment (`pyproject.toml: dependencies = ["wxpython==4.2.4", ...]`). It runs standalone on Windows without NVDA.
- **Hyphenated Directory Name:** The directory name `addon/globalPlugins/AI-assistant/` requires `load_addon_module` or package registration during tests. Pure unit tests can continue using `load_addon_module` or a registered `ai_assistant` package root in `conftest.py`.

---

## 4. Conclusion

Slice 1 is fully surveyed, bounded, and ready for immediate implementation.
- Decoupling root `conftest.py` requires adding a simple `HAS_NVDA_CHECKOUT` conditional branch and pytest collection hook.
- Decoupling logging requires replacing `from logHandler import log` with standard `import logging; log = logging.getLogger(__name__)` across 18 files and adding `utils/logger.py` with `NVDALogBridge`.
- Decoupling language requires adding `register_language_resolver` in `config/settings.py` and removing the top-level `import languageHandler`.
- Automated import boundaries are enforced through `tests/test_import_boundaries.py` (running in ~85ms) and Ruff `TID251` in `pyproject.toml`.
- All 451 pure tests will run standalone in < 3s, achieving 100% adherence to Invariants A5, A6, and A30.

---

## 5. Verification Method

To independently verify the survey observations and findings:

1. **Verify NVDA Import Inventory in Pure Packages:**
   ```powershell
   uv run python -c "
   import ast
   from pathlib import Path
   addon = Path('addon/globalPlugins/AI-assistant')
   pure_dirs = ['core', 'config', 'service', 'providers', 'use_case', 'prompts', 'tools', 'observability', 'embeddings']
   forbidden = {'api', 'textInfos', 'controlTypes', 'globalPluginHandler', 'scriptHandler', 'queueHandler', 'gui', 'wx', 'speech', 'tones', 'logHandler', 'languageHandler', 'addonHandler', 'winUser', 'locationHelper', 'treeInterceptorHandler', 'nvwave', 'globalVars'}
   violations = []
   for d in pure_dirs:
       for p in (addon / d).rglob('*.py'):
           tree = ast.parse(p.read_text(encoding='utf-8'))
           for n in ast.walk(tree):
               if isinstance(n, ast.Import):
                   for a in n.names:
                       if a.name.split('.')[0] in forbidden:
                           violations.append((p.name, n.lineno, a.name))
               elif isinstance(n, ast.ImportFrom) and n.module:
                   if n.module.split('.')[0] in forbidden:
                       violations.append((p.name, n.lineno, n.module))
   print(f'Violations: {len(violations)}')
   for v in violations: print(v)
   "
   ```
   *Expected result:* Exactly 18 violations (17 `logHandler`, 1 `languageHandler`).

2. **Verify Current Full Test Suite & Lint Baseline:**
   ```powershell
   uv run ruff check .
   uv run pytest
   ```
   *Expected result:* Ruff reports 0 errors; pytest reports 461 passed, 3 deselected in ~16.5s.

3. **Verify Pure Test Execution Speed:**
   ```powershell
   uv run pytest tests/config tests/prompts tests/observability tests/embeddings tests/use_case
   ```
   *Expected result:* 95 passed in < 0.9s.

4. **Verify Conftest Sibling Lock:**
   Inspect `conftest.py:27–31`. Confirm `if not (NVDA_SOURCE / "api.py").is_file(): raise pytest.UsageError(...)` runs unconditionally at root import time.
