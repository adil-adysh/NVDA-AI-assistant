# Handoff Report: Pure Python Test Boundary Decoupling (Slice 1)

**Agent:** Explorer 2 (Milestone 2, Slice 1)  
**Date:** 2026-10-04  
**Target Commit:** `ced1cbc` (HEAD)  
**Working Directory:** `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m2_explorer_2`  
**Deliverable Artifacts:** `analysis.md`, `handoff.md`  

---

## 1. Observation

1. **NVDA Log Filtering Mechanic (`filterExternalDependencyLogging`):**
   In `D:\nvda-addons\nvda\source\logHandler.py:605–612`:
   ```python
   def filterExternalDependencyLogging(record: logging.LogRecord) -> bool:
       import config

       return (
           record.name == NVDA_LOGGER_NAME
           or record.levelno >= Logger.WARNING
           or config.conf["debugLog"]["externalPythonDependencies"]
       )
   ```
   Where `NVDA_LOGGER_NAME = "nvda"` (`logHandler.py:524`).
   This filter is attached to NVDA's root `logHandler` on `log.root` (`logHandler.py:672–673`).
   Direct consequence: Standard library loggers emitting records where `record.name != "nvda"` have all `DEBUG` (level 10) and `INFO` (level 20) records silently dropped unless `externalPythonDependencies` is enabled in NVDA's user config.

2. **NVDA Formatter Dependency on `codepath`:**
   In `D:\nvda-addons\nvda\source\logHandler.py:631–634`:
   ```python
   logFormatter = Formatter(
       fmt="{levelname!s} - {codepath!s} ({asctime}) - {threadName} ({thread}):\n{message}",
       style="{",
   )
   ```
   And `Logger._log` (`logHandler.py:266–271`) sets `extra["codepath"] = codepath`. If `codepath` is not passed to `logHandler.log._log(...)`, NVDA inspects `f = inspect.currentframe().f_back.f_back`, which points to the caller inside any bridging handler.

3. **Current Inventory of `logHandler` Leaks in Pure Packages:**
   An exhaustive search across the codebase identified exactly 18 pure files importing `from logHandler import log`:
   - `addon/globalPlugins/AI-assistant/config/state.py:7`
   - `addon/globalPlugins/AI-assistant/config/yaml_store.py:10`
   - `addon/globalPlugins/AI-assistant/utils/crypto.py:20`
   - `addon/globalPlugins/AI-assistant/service/base.py:8`
   - `addon/globalPlugins/AI-assistant/service/model_cache.py:29`
   - `addon/globalPlugins/AI-assistant/service/error_reporter.py:10`
   - `addon/globalPlugins/AI-assistant/service/chat/coordinator.py:9`
   - `addon/globalPlugins/AI-assistant/service/chat/repository_backends.py:13`
   - `addon/globalPlugins/AI-assistant/providers/litert_manager.py:13`
   - `addon/globalPlugins/AI-assistant/providers/llama_manager.py:10`
   - `addon/globalPlugins/AI-assistant/providers/provider_proxy.py:7`
   - `addon/globalPlugins/AI-assistant/providers/_provider_runtime.py:7`
   - `addon/globalPlugins/AI-assistant/providers/adapters/openai_compat.py:23`
   - `addon/globalPlugins/AI-assistant/providers/runtime/download.py:27`
   - `addon/globalPlugins/AI-assistant/providers/runtime/manager.py:12`
   - `addon/globalPlugins/AI-assistant/providers/runtime/model_download.py:21`
   - `addon/globalPlugins/AI-assistant/prompts/base.py:7`
   - `addon/globalPlugins/AI-assistant/observability/reporter.py:7`
   All 18 invoke exclusively standard `Logger` methods (`debug`, `info`, `warning`, `error`, `exception`).

4. **Language Handler Contamination in `config/settings.py`:**
   In `addon/globalPlugins/AI-assistant/config/settings.py:8`:
   ```python
   import languageHandler
   ```
   And in `get_effective_language()` (`settings.py:198–201`):
   ```python
   language_value = get_language()
   if not language_value or language_value == defaults.DEFAULT_LANGUAGE:
       language_value = languageHandler.getLanguage() or "en"
   ```
   No other file in `addon/` imports `languageHandler`.

5. **Existing Test Suite Baseline:**
   `uv run pytest -m "not nvda_integration"`: 461 passed, 3 deselected in 13.29s.

---

## 2. Logic Chain

1. **Premise:** Pure Python packages (`core/`, `config/`, `service/`, `providers/`, `prompts/`, `tools/`, `observability/`, `embeddings/`) must be executable without NVDA or `../nvda` checkout (Invariants A5, A6, A30).
2. **From Observation 3:** The 18 files import `from logHandler import log` directly at module scope. If NVDA is not on `sys.path`, module evaluation raises `ModuleNotFoundError: No module named 'logHandler'`.
3. **From Observation 4:** `config/settings.py` imports `languageHandler` at line 8. If NVDA is not on `sys.path`, importing settings raises `ModuleNotFoundError: No module named 'languageHandler'`.
4. **From Observation 1:** Simply replacing `from logHandler import log` with `import logging; log = logging.getLogger(__name__)` causes NVDA's `filterExternalDependencyLogging` to suppress `DEBUG` and `INFO` records because `record.name != "nvda"`.
5. **Deduction:** An adapter bridge (`NVDALogBridge`) is required when running inside NVDA. By routing records via `logHandler.log._log(level, msg, (), codepath=codepath, ...)`, the resulting record carries `name == "nvda"`, bypassing the external dependency filter and reaching NVDA's log file with accurate caller `codepath`.
6. **Deduction on Cycle & Duplication:** Routing via `logHandler.log` creates records that propagate to `logging.root`. To prevent infinite loops, `NVDALogBridge.emit` must guard against `record.name == "nvda"` and `record._nvda_bridged == True`. To prevent duplicate WARNING/ERROR entries on NVDA's root handler, a filter `_drop_bridged_filter` must be installed on NVDA's `logHandler`.
7. **Deduction on Language Port:** Replacing top-level `import languageHandler` in `config/settings.py` with `register_language_resolver(resolver: Callable[[], str] | None)` and lazy fallback uncouples the settings domain module completely, enabling pure-Python test environments to run without NVDA stubs.

---

## 3. Caveats

1. **Adapter Layer Retentions:** The 22 `logHandler` imports in `context/extractors/`, `image/`, `plugin/`, `ui/`, and `utils/clipboard.py` remain intact in this slice as they are explicitly Layer 0 / NVDA-affine adapter surfaces.
2. **Third-Party External Logging:** The `NVDALogBridge` attaches to the root logger or add-on package logger in NVDA. It does not alter logging from unrelated external third-party libraries unless attached at root.
3. **Pure Tests with languageHandler:** Tests in `tests/config/test_settings_activation.py` and `tests/providers/test_litert_manager.py` that currently monkeypatch `languageHandler.getLanguage` should be updated to use `register_language_resolver` or guard their monkeypatching when `languageHandler` is not present.

---

## 4. Conclusion

1. **`addon/globalPlugins/AI-assistant/utils/logger.py` Design:** Fully specified with `NVDALogBridge(logging.Handler)`, cycle prevention, duplication filter, `codepath` preservation, and pure-environment no-op fallback.
2. **Pure Package Logging Purge:** Complete, exact before/after specifications provided for all 18 pure modules. Pure code requires only `import logging; log = logging.getLogger(__name__)`.
3. **Language Resolver Port:** Complete implementation specified for `config/settings.py:register_language_resolver` and `get_effective_language()` lazy fallback, with host wiring in `plugin/__init__.py` and `plugin/application.py`.

---

## 5. Verification Method

1. **Code Purity & Linting:**
   ```powershell
   uv run ruff check .
   ```
   Must pass with 0 errors with `TID251` enabled on pure packages.
2. **AST Boundary Test:**
   ```powershell
   uv run pytest tests/test_import_boundaries.py
   ```
   Must pass with 0 forbidden NVDA imports across pure packages.
3. **Pure Test Suite Without NVDA:**
   ```powershell
   uv run pytest -m "not nvda_integration"
   ```
   Must execute cleanly (461+ items) in < 15 seconds without dependency on `../nvda/source/api.py`.
4. **Log Bridging Verification in NVDA:**
   Start NVDA with `--debug-logging`, trigger a pure domain action (e.g. settings load, model cache query), and verify that `DEBUG` and `INFO` records appear in `nvda.log` with correct `codepath` and no duplicate entries.
