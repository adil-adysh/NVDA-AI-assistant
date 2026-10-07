# Forensic Audit Report — Milestone 2 (Slice 1: Pure Python Test Boundary Decoupling & Import Enforcement)

**Work Product**: Milestone 2 (Slice 1 Implementation)
**Profile**: General Project (Development Mode per ORIGINAL_REQUEST.md line 106)
**Verdict**: **INTEGRITY VIOLATION**

---

## 1. Observation

Direct code-level and command execution observations:

### Observation 1.1: Transitive `logHandler` Contamination via `utils/__init__.py`
- In `addon/globalPlugins/AI-assistant/utils/__init__.py`:
  - Line 4: `from .clipboard import safe_read_clipboard`
- In `addon/globalPlugins/AI-assistant/utils/clipboard.py`:
  - Line 11: `from logHandler import log`
- In `addon/globalPlugins/AI-assistant/config/yaml_store.py`:
  - Line 12: `from ..utils.crypto import decrypt_value, encrypt_value, is_encrypted, is_sensitive_key`
- Verbatim execution error when attempting to import `config.yaml_store` in pure isolation:
  ```
  Traceback (most recent call last):
    File "<string>", line 1, in <module>
      from tests.support import load_addon_module; mod = load_addon_module('config.yaml_store', namespace='pure_test')
    File "D:\nvda-addons\NVDA-AI-assistant\tests\support\bootstrap.py", line 60, in load_addon_module
      return load_module(".".join((namespace, *parts)), module_path)
    File "D:\nvda-addons\NVDA-AI-assistant\tests\support\bootstrap.py", line 45, in load_module
      spec.loader.exec_module(module)
    File "D:\nvda-addons\NVDA-AI-assistant\addon\globalPlugins\AI-assistant\config\yaml_store.py", line 12, in <module>
      from ..utils.crypto import decrypt_value, encrypt_value, is_encrypted, is_sensitive_key
    File "D:\nvda-addons\NVDA-AI-assistant\addon\globalPlugins\AI-assistant\utils\__init__.py", line 4, in <module>
      from .clipboard import safe_read_clipboard
    File "D:\nvda-addons\NVDA-AI-assistant\addon\globalPlugins\AI-assistant\utils\clipboard.py", line 11, in <module>
      from logHandler import log
  ModuleNotFoundError: No module named 'logHandler'
  ```
  This transitive contamination affects all pure domain and service modules importing `config.settings` or `config.yaml_store`, including `service.chat.coordinator` and `providers.litert_manager`.

### Observation 1.2: Test Suite Aborts Collection When Sibling NVDA Checkout Is Absent
- When `HAS_NVDA_CHECKOUT` evaluates to `False` (simulating the absence of `../nvda` checkout per acceptance criteria):
  Command executed:
  `uv run python -c "import pathlib, pytest; orig = pathlib.Path.is_file; pathlib.Path.is_file = lambda self: False if 'api.py' in str(self) else orig(self); ret = pytest.main(['-m', 'not nvda_integration']); print('EXIT CODE:', ret)"`
- Verbatim tool output:
  ```
  ERROR tests/architecture/test_use_case_flow.py
  ERROR tests/config/test_yaml_store.py
  ERROR tests/integration/test_chat_lifecycle.py
  ERROR tests/plugin/test_background_provider_ready.py
  ERROR tests/plugin/test_background_shutdown.py
  ERROR tests/plugin/test_presenter_ui_actions.py
  ERROR tests/providers/test_llama_provider.py
  ERROR tests/ui/test_adapter_fallback.py
  !!!!!!!!!!!!!!!!!!! Interrupted: 8 errors during collection !!!!!!!!!!!!!!!!!!!
  ====================== 17 deselected, 8 errors in 0.57s =======================
  EXIT CODE: 2
  ```
- 8 test modules fail collection with `ModuleNotFoundError: No module named 'logHandler'` because they are not gated by `pytestmark = pytest.mark.nvda_integration` and import modules that directly or transitively depend on `logHandler`.

### Observation 1.3: `NVDALogBridge` Is Unwired Dead Code in Production
- In `addon/globalPlugins/AI-assistant/utils/logger.py`:
  - Line 26: `class NVDALogBridge(logging.Handler): ...`
  - Line 68: `def attach_nvda_log_bridge(logger_name: str | None = None) -> bool: ...`
- Grep across the entire repository for `attach_nvda_log_bridge` yields only two hits:
  ```
  addon\globalPlugins\AI-assistant\utils\logger.py:8: When running inside NVDA, `attach_nvda_log_bridge()` connects standard
  addon\globalPlugins\AI-assistant\utils\logger.py:68: def attach_nvda_log_bridge(logger_name: str | None = None) -> bool:
  ```
- `attach_nvda_log_bridge` is NEVER called anywhere in `addon/globalPlugins/AI-assistant/plugin/controller.py`, `addon/globalPlugins/AI-assistant/plugin/application.py`, or any other runtime startup code.
- Consequently, in production NVDA, `NVDALogBridge` is never installed. Standard library `log.debug()`, `log.info()`, `log.warning()`, `log.error()`, and `log.exception()` calls in all 18 decoupled pure modules are never forwarded to NVDA's `logHandler.log` (`nvda.log`).
- Furthermore, `attach_nvda_log_bridge` fails to configure the target logger's level (which defaults to `WARNING` in stdlib Python), meaning that even if attached, DEBUG and INFO records would be discarded by `Logger.isEnabledFor()` before reaching `NVDALogBridge.emit()`.

### Observation 1.4: `register_language_resolver` Is Unwired in Production NVDA
- In `addon/globalPlugins/AI-assistant/config/settings.py`:
  - Line 27: `def register_language_resolver(resolver: Callable[[], str] | None) -> None:`
  - Line 206:
    ```python
    def get_effective_language() -> str:
        language_value = get_language()
        if not language_value or language_value == defaults.DEFAULT_LANGUAGE:
            if _language_resolver is not None:
                try:
                    return _language_resolver() or "en"
                except Exception:
                    return "en"
            return "en"
        return language_value
    ```
- Grep across the repository confirms `register_language_resolver` is ONLY called in test files (`tests/config/test_settings_activation.py` and `tests/providers/test_litert_manager.py`). It is NEVER called in `plugin/controller.py` or `plugin/application.py`.
- In production NVDA, `_language_resolver` is permanently `None`, causing `get_effective_language()` to always fall back to `"en"` regardless of NVDA's active user language.

### Observation 1.5: AST Import Scanner Verification
- In `tests/test_import_boundaries.py`:
  - `_find_forbidden_imports` correctly parses AST with `ast.parse` and walks AST nodes (`ast.Import`, `ast.ImportFrom`, and `ast.Call` for dynamic imports).
  - Tested against synthetic code containing `import api`, `from logHandler import log`, `__import__('speech')`, and `importlib.import_module('wx')`: correctly flags all 4 violations.
  - However, `tests/test_import_boundaries.py` only scans `PURE_DIRECTORIES` and 10 specific files in `context/`. It does NOT scan `utils/` or test runtime imports, masking the transitive contamination from `utils/__init__.py`.

### Observation 1.6: Ruff TID251 Banned API Verification
- In `pyproject.toml` lines 83–104:
  - `TID251` is enabled in `extend-select`.
  - Banned APIs configured for `logHandler`, `languageHandler`, `api`, `textInfos`, `controlTypes`, `globalPluginHandler`, `scriptHandler`, `queueHandler`, `gui`, `wx`, `speech`, `tones`.
  - Tested against synthetic files in `core/`: Ruff immediately flags `TID251` violations with non-zero exit code.
  - Current repository state: `uv run ruff check .` passes with 0 errors.

---

## 2. Logic Chain

1. **Requirement Check against ORIGINAL_REQUEST.md (§R2 & Acceptance Criteria)**:
   - Acceptance Criterion 1: "`uv run pytest -m "not nvda_integration"` succeeds even if `../nvda` is absent or uninitialized."
   - Acceptance Criterion 2: "Pure Python packages import without requiring NVDA modules."
   - Acceptance Criterion 3: "Isolate NVDA `logHandler` dependencies in pure domain modules (`core/`, `config/`, `service/`, `providers/`, `use_case/`) by introducing a standard library `logging.getLogger` fallback/facade."
2. **Evaluation of Acceptance Criterion 1**:
   - Observation 1.2 shows that when the sibling checkout is absent (`HAS_NVDA_CHECKOUT = False`), executing `pytest -m "not nvda_integration"` immediately encounters 8 collection errors and terminates with exit code 2.
   - **Step Conclusion**: Acceptance Criterion 1 fails empirically.
3. **Evaluation of Acceptance Criterion 2**:
   - Observation 1.1 shows that importing pure package `config.yaml_store` (and by extension any pure module that touches configuration) causes Python to load `addon.globalPlugins.AI-assistant.utils`. This triggers `utils/__init__.py`, which imports `utils/clipboard.py`, which executes `from logHandler import log`.
   - Without `logHandler` available, this import crashes with `ModuleNotFoundError`.
   - **Step Conclusion**: Pure Python packages cannot import without requiring NVDA modules. Acceptance Criterion 2 fails empirically.
4. **Evaluation of Logging Decoupling & Bridge Contract**:
   - The architectural specification and `PROJECT.md` require that pure modules use `logging.getLogger(__name__)` while an adapter layer connects `NVDALogBridge` to route records to `logHandler.log`.
   - Observation 1.3 shows that while the 18 files were changed to `logging.getLogger(__name__)`, `attach_nvda_log_bridge()` was never integrated into NVDA plugin startup.
   - As a result, in production NVDA, `NVDALogBridge` is dead code. All production logs from the 18 pure modules are silently dropped.
   - **Step Conclusion**: `NVDALogBridge` is an unwired facade implementation.
5. **Evaluation of Language Resolver Contract**:
   - Observation 1.4 shows `register_language_resolver` was introduced and wired in two test files, but never wired in production NVDA startup.
   - Production NVDA users with non-English interfaces have prompt generation forced to English.
   - **Step Conclusion**: Unwired port implementation causing functional regression in production.
6. **Integrity Rule Evaluation**:
   - Under Teamwork Integrity Forensics: "Facade implementations: Correct-looking interfaces with no genuine logic" and "Block on failure: If ANY check fails, the verdict is INTEGRITY VIOLATION and the work product must be rejected."
   - Because of the facade/unwired logging bridge, the unwired language resolver, the transitive `logHandler` contamination, and the total failure of standalone test execution when `../nvda` is absent, the work product cannot be certified.

---

## 3. Caveats

- `uv run ruff check .` currently passes with 0 errors.
- `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml` passes with 20/20 tests (Slice 0 remains clean).
- `cargo check --manifest-path nvda_ui_host/Cargo.toml` passes cleanly.
- `tests/test_import_boundaries.py` genuinely executes AST parsing and passes for the files it checks, but has a blind spot regarding transitive package imports through `utils/`.
- No caveats regarding the observed failures; all failures were reproduced directly with raw tool outputs.

---

## 4. Conclusion

The work product for Milestone 2 (Slice 1) contains critical integrity violations and incomplete implementations:
1. **Facade / Dead-Code Bridge**: `NVDALogBridge` is never attached in production; logs from pure modules are discarded.
2. **Unwired Language Resolver**: `register_language_resolver` is never called in production; localization falls back to `"en"`.
3. **Transitive Import Contamination**: `utils/__init__.py` imports `clipboard.py` which imports `logHandler`, contaminating all pure modules that import `utils.crypto`.
4. **Broken Acceptance Criteria**: `uv run pytest -m "not nvda_integration"` fails with 8 collection errors when `../nvda` checkout is absent.

**Formal Verdict**: **INTEGRITY VIOLATION** (Work product is REJECTED).

### Actionable Remediation Required:
1. In `addon/globalPlugins/AI-assistant/utils/__init__.py`: Remove `from .clipboard import safe_read_clipboard` (or make it lazy/optional so importing `utils.crypto` does not load `clipboard.py`).
2. In `addon/globalPlugins/AI-assistant/plugin/application.py` (or `controller.py`):
   - Call `attach_nvda_log_bridge()` during plugin startup to genuinely connect pure domain loggers to `logHandler.log`.
   - Call `register_language_resolver(languageHandler.getLanguage)` during plugin startup.
3. In `addon/globalPlugins/AI-assistant/utils/logger.py`: In `attach_nvda_log_bridge()`, ensure target logger level is set to `logging.DEBUG` so debug/info records are dispatched to the bridge.
4. Gate all plugin/presentation test files that load NVDA-dependent plugin modules (`tests/architecture/test_use_case_flow.py`, `tests/plugin/test_background_provider_ready.py`, `tests/plugin/test_background_shutdown.py`, `tests/plugin/test_presenter_ui_actions.py`, `tests/ui/test_adapter_fallback.py`) with `pytestmark = pytest.mark.nvda_integration`, or decouple them from top-level `logHandler`.

---

## 5. Verification Method

To independently reproduce and verify this finding:

1. **Reproduce Transitive Contamination**:
   ```pwsh
   uv run python -c "from tests.support import load_addon_module; mod = load_addon_module('config.yaml_store', namespace='pure_test')"
   ```
   *Expected result*: Fails with `ModuleNotFoundError: No module named 'logHandler'`.

2. **Reproduce Missing Checkout Test Failure**:
   ```pwsh
   uv run python -c "import pathlib, pytest; orig = pathlib.Path.is_file; pathlib.Path.is_file = lambda self: False if 'api.py' in str(self) else orig(self); ret = pytest.main(['-m', 'not nvda_integration']); print('EXIT CODE:', ret)"
   ```
   *Expected result*: Aborts during collection with 8 errors and `EXIT CODE: 2`.

3. **Verify Unwired `attach_nvda_log_bridge`**:
   ```pwsh
   git grep "attach_nvda_log_bridge"
   ```
   *Expected result*: Only matches its docstring and definition in `utils/logger.py`. Zero production call sites.

4. **Verify Unwired `register_language_resolver`**:
   ```pwsh
   git grep "register_language_resolver"
   ```
   *Expected result*: Zero production call sites in `plugin/controller.py` or `plugin/application.py`.
