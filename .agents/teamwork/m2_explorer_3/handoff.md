# Handoff Report: Milestone 2 Slice 1 (AST Boundary Tests & Ruff TID251)

**From:** Explorer 3 (`m2_explorer_3`)  
**To:** Orchestrator (`72553112-d803-4b0c-aef3-2a3e71303bdb`) / Implementation Lead  
**Task:** Slice 1 — Pure Python Test Boundary Decoupling (AST Test Design & Ruff Configuration)  
**Date:** 2026-10-04  
**Type:** Hard Handoff (Investigation Complete)

---

## 1. Observation

1. **AST Scan Scope & Timing:**
   - 97 Python files exist under pure packages (`core/`, `config/`, `service/`, `providers/`, `use_case/`, `prompts/`, `tools/`, `observability/`, `embeddings/`) totaling 69,043 AST nodes.
   - Parsing all 97 files with `ast.parse` and walking nodes took **81.69 ms** in python 3.13. Parsing 10 pure context files took **8.88 ms**. Combined scan time is **90.57 ms**, well beneath the **< 150 ms** requirement.
   - Running an existing AST architecture test (`tests/architecture/test_thread_boundaries.py`) in pytest reported:
     ```
     tests\architecture\test_thread_boundaries.py ....                        [100%]
     ============================== 4 passed in 0.02s ==============================
     ```

2. **Forbidden Imports in Pure Packages at HEAD (`ced1cbc`):**
   - AST search across all 9 pure packages identified exactly 18 occurrences of forbidden NVDA imports:
     - `config/settings.py:8` -> `import languageHandler`
     - 17 files importing `from logHandler import log`: `config/state.py:7`, `config/yaml_store.py:10`, `observability/reporter.py:7`, `prompts/base.py:7`, `providers/_provider_runtime.py:7`, `providers/adapters/openai_compat.py:23`, `providers/litert_manager.py:13`, `providers/llama_manager.py:10`, `providers/provider_proxy.py:7`, `providers/runtime/download.py:27`, `providers/runtime/manager.py:12`, `providers/runtime/model_download.py:21`, `service/base.py:8`, `service/chat/coordinator.py:9`, `service/chat/repository_backends.py:13`, `service/error_reporter.py:10`, `service/model_cache.py:29`.
   - In `utils/`: `utils/crypto.py:20` also imports `from logHandler import log`.
   - Zero occurrences of `api`, `textInfos`, `controlTypes`, `globalPluginHandler`, `scriptHandler`, `queueHandler`, `gui`, `wx`, `speech`, or `tones` exist in any pure package.

3. **`context/navigation.py` Discovery:**
   - `addon/globalPlugins/AI-assistant/context/navigation.py` contains:
     - Line 559: `import api` (inside `_tree_interceptor`)
     - Line 610: `import winUser` (inside `_restore_browser_focus`)
     - Line 635: `import textInfos` (inside `resolve_and_move_target`)
   - Running `ruff check` with `TID251` enabled without `context/navigation.py` in `per-file-ignores` produced:
     ```
     TID251 `api` is banned: NVDA api access is forbidden outside Layer 0 adapter surfaces.
        --> addon\globalPlugins\AI-assistant\context\navigation.py:559:10
     TID251 `textInfos` is banned: textInfos is forbidden outside Layer 0 adapter surfaces.
        --> addon\globalPlugins\AI-assistant\context\navigation.py:635:10
     Found 2 errors.
     ```

4. **Root `conftest.py` Discovery:**
   - Root `conftest.py` contains lines 82–84:
     ```python
     import controlTypes  # noqa: E402, F401
     import logHandler  # noqa: E402, F401
     import textInfos  # noqa: E402, F401
     ```
   - Running `ruff check` with `per-file-ignores` set to `"tests/**" = ["TID251"]` resulted in:
     ```
     TID251 `controlTypes` is banned
       --> conftest.py:82:8
     TID251 `logHandler` is banned
       --> conftest.py:83:8
     TID251 `textInfos` is banned
       --> conftest.py:84:8
     ```
     Proving that `"tests/**"` does not cover repo-root `conftest.py`.

5. **Ruff Validation with Candidate Configuration:**
   - Running `uv run ruff check . --config .agents/teamwork/m2_explorer_3/candidate_ruff.toml` (which includes `context/navigation.py`, `conftest.py`, and adapter paths in `per-file-ignores`) yielded **exactly 19 errors** (the 18 pure package violations + `utils/crypto.py`) and **0 false positives**.

---

## 2. Logic Chain

1. From Observation 1, scanning 97 files + 10 context files via Python `ast` takes ~90 ms. Adding pytest test runner overhead (~20 ms) gives ~110 ms total execution time, satisfying the `< 150 ms` performance SLA.
2. From Observation 2, the only forbidden imports currently present in pure packages are 17 `logHandler` and 1 `languageHandler`. Once replaced with `import logging; log = logging.getLogger(__name__)` and `register_language_resolver`, both the AST test and Ruff `TID251` will pass cleanly.
3. From Observation 3, `context/navigation.py` performs browser document focus manipulation and legitimately calls `api` and `textInfos`. Because it lives in `context/` rather than `context/extractors/`, omitting it from `per-file-ignores` causes immediate lint failures. Therefore, `"addon/globalPlugins/AI-assistant/context/navigation.py" = ["TID251"]` must be included.
4. From Observation 4, `conftest.py` is at repository root. Glob patterns matching `"tests/**"` do not match `./conftest.py`. Therefore, `"conftest.py" = ["TID251"]` must be explicitly added to `per-file-ignores`.
5. From Observation 5, the candidate configuration accurately isolates Layer 0 adapters from pure code, flagging every violation in pure code while permitting necessary host access in adapter modules.

---

## 3. Caveats

1. **Prerequisite Decoupling:** The AST test and Ruff `TID251` rule cannot pass on HEAD (`ced1cbc`) until the 18 pure files + `utils/crypto.py` have their `logHandler` and `languageHandler` imports decoupled. They must be merged in the same slice/commit or immediately after the logger/language decoupling.
2. **`utils/logger.py` Bridge:** When `utils/logger.py` is created to define `NVDALogBridge`, it will import `from logHandler import log`. It must either carry `# noqa: TID251` or have `"addon/globalPlugins/AI-assistant/utils/logger.py" = ["TID251"]` in `per-file-ignores`. Both mechanisms have been documented in `analysis.md`.
3. **No Dynamic Code Modification:** As an explorer, no changes have been committed directly to `pyproject.toml` or `tests/`. All deliverables are ready for direct drop-in by the implementer.

---

## 4. Conclusion

1. **`tests/test_import_boundaries.py` is fully designed and benchmarked:**
   - Asserts zero forbidden imports for `api`, `textInfos`, `controlTypes`, `globalPluginHandler`, `scriptHandler`, `queueHandler`, `gui`, `wx`, `speech`, `tones`, `logHandler`, `languageHandler`, and extended NVDA runtime modules.
   - Includes 3 tests: pure packages check, pure context files check, and performance check (< 150ms).
   - Drop-in implementation code is provided in `analysis.md §2.4`.
2. **Ruff `TID251` configuration in `pyproject.toml` is verified and ready:**
   - Adds `TID251` to `extend-select`.
   - Configures `[tool.ruff.lint.flake8-tidy-imports.banned-api]` for all 12 NVDA modules.
   - Configures `[tool.ruff.lint.per-file-ignores]` with all Layer 0 adapters PLUS `context/navigation.py` and `conftest.py`.
   - Drop-in TOML snippet is provided in `analysis.md §3.1`.

---

## 5. Verification Method

To independently verify after the implementer applies the changes:

1. **Lint Verification:**
   ```powershell
   uv run ruff check .
   ```
   *Expected result:* 0 errors, all checks passed.

2. **AST Boundary Test Execution:**
   ```powershell
   uv run pytest tests/test_import_boundaries.py -v
   ```
   *Expected result:* 3 passed in < 0.20s (with performance test asserting < 150ms).

3. **Pure Python Suite Execution (No NVDA Required):**
   ```powershell
   uv run pytest -m "not nvda_integration"
   ```
   *Expected result:* All 451 pure tests pass.

4. **Invalidation Conditions:**
   - Any commit that re-introduces `from logHandler import log` or `import api` into any pure package must cause both `uv run ruff check .` and `uv run pytest tests/test_import_boundaries.py` to fail with exit code 1.
