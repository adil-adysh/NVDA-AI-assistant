# Handoff Report: Pure Python Test Boundary Decoupling (Slice 1)

**Agent:** Explorer 1 (`m2_explorer_1`)  
**Handoff Type:** Hard (Task complete)  
**Recipient:** Orchestrator (`72553112-d803-4b0c-aef3-2a3e71303bdb`)  
**Date:** 2026-10-04  

---

## 1. Observation

1. **Unconditional Collection Blockade in `conftest.py`:**
   At `conftest.py:27–31`:
   ```python
   if not (NVDA_SOURCE / "api.py").is_file():
   	raise pytest.UsageError(
   		"NVDA source checkout was not found at ../nvda. "
   		"Clone https://github.com/nvaccess/nvda.git beside NVDA-AI-assistant.",
   	)
   ```
   Executing `pytest` when `../nvda` is missing raises `pytest.UsageError` immediately at module import time before test collection or marker filtering (`-m "not nvda_integration"`) can occur.

2. **Unconditional Git Revision Verification:**
   At `conftest.py:33–40`:
   ```python
   revision = subprocess.run(
   	["git", "rev-parse", "HEAD"],
   	cwd=NVDA_ROOT,
   	check=True,
   	capture_output=True,
   	text=True,
   ).stdout.strip()
   ```
   If `NVDA_ROOT` does not exist or is not a git repository, this raises an unhandled `FileNotFoundError` or `CalledProcessError`.

3. **Absence of Integration Markings on Real NVDA Tests:**
   - `tests/integration/test_nvda_imports.py:7`:
     ```python
     from conftest import NVDA_ROOT, NVDA_SOURCE, PROJECT_ROOT, REAL_NVDA_MODULES
     ```
     Contains 3 test functions asserting real NVDA paths and `controlTypes.Role.BUTTON`, but lacks `pytestmark = pytest.mark.nvda_integration`.
   - `tests/context/extractors/test_browser_field_parser.py:6, 14`:
     ```python
     import controlTypes
     ...
     Role = controlTypes.Role
     ```
     Contains 7 test functions testing NVDA `getTextWithFields` parsing using `controlTypes.Role`, but lacks `pytestmark = pytest.mark.nvda_integration`.

4. **Module Collection Import Failure on Unguarded `controlTypes`:**
   Empirical testing with simulated missing checkout revealed:
   ```
   ERROR collecting test_browser_field_parser.py
   ModuleNotFoundError: No module named 'controlTypes'
   Interrupted: 1 error during collection!
   ```
   Adding solely `pytestmark = pytest.mark.nvda_integration` without guarding `import controlTypes` causes pytest collection to abort with exit code 2 before `pytest_collection_modifyitems` can execute.

5. **Hidden NVDA Extractor Coupling in `tests/context/test_browser_field_graph.py`:**
   At `tests/context/test_browser_field_graph.py:18`:
   ```python
   parser_module = load_module(f"{PACKAGE}.extractors.browser_field_parser", ROOT / "extractors" / "browser_field_parser.py")
   ```
   `browser_field_parser.py:8` executes `import controlTypes` and `from textInfos import POSITION_ALL`. When `HAS_NVDA_CHECKOUT` is False, `test_browser_field_graph.py` fails during collection with `ModuleNotFoundError: No module named 'controlTypes'`.

6. **External Test Dependencies on `languageHandler`:**
   - `tests/config/test_settings_activation.py:13`: `import languageHandler`
   - `tests/providers/test_litert_manager.py:17`: `import languageHandler`
   Both monkeypatch `languageHandler.getLanguage` to `"en"`. Without `../nvda` on `sys.path`, both fail with `ModuleNotFoundError: No module named 'languageHandler'`.

---

## 2. Logic Chain

1. **Premise 1 (Decoupling `conftest.py`):**
   - Observations 1 and 2 show that `conftest.py` currently crashes pytest unconditionally if `../nvda` is missing.
   - Introducing `HAS_NVDA_CHECKOUT = (NVDA_SOURCE / "api.py").is_file()` allows conditional branching.
   - Moving git verification, `sys.path` injection, `globalVars` configuration, and `REAL_NVDA_MODULES` imports into `if HAS_NVDA_CHECKOUT:` enables pytest to start in standalone mode without requiring `../nvda`.
   - Moving builtins translation installation (`builtins._ = gettext.gettext`, etc.) outside the conditional ensures standalone pure tests never suffer `NameError: name '_' is not defined`.
   - Defining `REAL_NVDA_MODULES: dict[str, object] = {}` unconditionally ensures tests importing `REAL_NVDA_MODULES` from `conftest` do not fail on import.

2. **Premise 2 (Collection Hook Behavior):**
   - Implementing `pytest_collection_modifyitems` with:
     ```python
     if not HAS_NVDA_CHECKOUT:
         skip_marker = pytest.mark.skip(
             reason="Sibling NVDA checkout not found at ../nvda. Pure tests pass without it."
         )
         for item in items:
             if "nvda_integration" in item.keywords:
                 item.add_marker(skip_marker)
     ```
     ensures that any test tagged with `nvda_integration` is cleanly skipped (with an informative reason) if executed without the sibling checkout.

3. **Premise 3 (Import Guarding for Integration Tests):**
   - Observation 4 proves that pytest imports every test file during discovery. If a test file has an un-guarded `import controlTypes`, discovery crashes with exit code 2 before markers can be evaluated.
   - Therefore, `tests/context/extractors/test_browser_field_parser.py` must guard its `controlTypes` import using `try: import controlTypes; Role = controlTypes.Role except ImportError: controlTypes = None; Role = None`.
   - When guarded, collection succeeds without error, items receive the `nvda_integration` mark, and `-m "not nvda_integration"` deselects them.

4. **Premise 4 (Gating Additional Hidden Couplings):**
   - Observation 5 establishes that `tests/context/test_browser_field_graph.py` also loads `browser_field_parser.py`.
   - Wrapping that loader in `try...except ImportError` and marking `test_browser_field_graph.py` with `pytestmark = pytest.mark.nvda_integration` prevents collection failure.

---

## 3. Caveats

1. **Downstream Dependency on Feature 9, 10, 11 (Explorer 2's Scope):**
   Pure domain modules currently contain 17 occurrences of `from logHandler import log` and 1 occurrence of `import languageHandler` in `config/settings.py`. Full standalone execution of pure tests without dummy stubs requires Explorer 2's logging purge and language resolver decoupling (`register_language_resolver`).
2. **`test_settings_activation.py` and `test_litert_manager.py` Refactoring:**
   Once `register_language_resolver` is introduced, `tests/config/test_settings_activation.py` and `tests/providers/test_litert_manager.py` must be updated to call `register_language_resolver(lambda: "en")` instead of importing `languageHandler`.

---

## 4. Conclusion

1. Root `conftest.py` must be updated with `HAS_NVDA_CHECKOUT`, unconditional builtins/stubs, and `pytest_collection_modifyitems`.
2. `tests/integration/test_nvda_imports.py` and `tests/context/extractors/test_browser_field_parser.py` must be marked with `pytestmark = pytest.mark.nvda_integration`.
3. `tests/context/extractors/test_browser_field_parser.py` must wrap `import controlTypes` in `try...except ImportError` to prevent collection-time crashes.
4. `tests/context/test_browser_field_graph.py` should also be marked with `pytestmark = pytest.mark.nvda_integration` and wrapped against `ImportError`.
5. Complete compile-ready unified git diffs are provided in `analysis.md` (Sections 4.1–4.4).

---

## 5. Verification Method

To independently verify these findings:

1. **Verify Baseline Test Execution (Connected Mode):**
   ```powershell
   uv run pytest
   ```
   Expected: 461 passed, 3 deselected in ~13s.

2. **Verify Integration Suite Execution (Connected Mode):**
   ```powershell
   uv run pytest -m nvda_integration
   ```
   Expected: All integration tests pass.

3. **Verify Pure Test Standalone Execution (Simulated Absent Checkout):**
   Run the empirical test runner developed during this investigation:
   ```powershell
   uv run python .agents/teamwork/m2_explorer_1/test_comprehensive_conftest.py
   ```
   Expected:
   - Mode A (`-m "not nvda_integration"`): 0 errors, pure tests run.
   - Mode B (`-m "nvda_integration"`): 0 errors, integration tests skipped with reason: `"Sibling NVDA checkout not found at ../nvda. Pure tests pass without it."`.
   - Mode C (Direct test execution): 0 errors, integration tests skipped.
   - Output terminates with `ALL TEST MODES PASSED SUCCESSFULLY!`.

4. **Verify Parser Test Gating:**
   ```powershell
   uv run python .agents/teamwork/m2_explorer_1/test_browser_parser_verification.py
   ```
   Expected: Exit code 0 across missing checkout scenarios.
