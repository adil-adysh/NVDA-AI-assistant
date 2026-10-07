# Handoff Report: AST Boundary Tests & Ruff Banned API Fix Strategy

**Author**: Milestone 2 Explorer 3 (Iteration 2) (`m2_explorer_3_gen2`)  
**Scope**: Concrete Fix Strategy for AST Boundary Tests (`tests/test_import_boundaries.py`), Ruff Banned API Rules (`pyproject.toml`), Pure Utils Files, Relative Imports, and Layer 0 Leaks  
**Target Milestone**: Milestone 2 (Slice 1 Pure Python Test Boundary Decoupling & Import Enforcement)  
**Handoff Type**: Hard (Task Complete)  

---

## 1. Observation

Direct code-level and empirical observations from the codebase:

### Obs 1: Pure Utils Files Unchecked in AST Test
- In `addon/globalPlugins/AI-assistant/utils/`:
  - `crypto.py`: Uses Windows DPAPI via `ctypes` and `logging.getLogger(__name__)`. 0 NVDA imports.
  - `markdown.py`: Uses `html.escape` and `markdown`. 0 NVDA imports.
  - `mathml.py`: Uses pure regex/string parsing and optional `latex2mathml`. 0 NVDA imports.
  - `clipboard.py`: Layer 0 adapter importing `api.getClipData()` and `from logHandler import log`.
  - `logger.py`: Layer 0 adapter bridging to `logHandler.log`.
- In `tests/test_import_boundaries.py`:
  - Lines 15–25 define `PURE_DIRECTORIES` (`core`, `config`, `service`, `providers`, `use_case`, `prompts`, `tools`, `observability`, `embeddings`).
  - Lines 27–38 define `PURE_CONTEXT_FILES` (10 files).
  - Pure utility files (`crypto.py`, `markdown.py`, `mathml.py`) are **omitted** from both definitions and are never scanned by the boundary test.

### Obs 2: AST Scanner Evasion Flaws
- In `tests/test_import_boundaries.py`:
  - Line 76: `raw_bytes = file_path.read_bytes(); if not any(token in raw_bytes for token in FORBIDDEN_BYTES): return []` suppresses AST parsing when byte tokens are hex/unicode-escaped (`\x61pi`).
  - Line 91: `elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:` explicitly suppresses detection on all relative imports where `node.level > 0`.
  - Lines 97–115: `ast.Call` inspection checks only positional `node.args[0]` on `node.func.id == "__import__"` and `node.func.attr == "import_module"`, missing keyword arguments `name="api"`, direct calls `import_module("api")`, and qualified calls `builtins.__import__("api")`.
- Benchmarking direct AST parsing across all 110 pure domain files without pre-filter yielded an execution time of **60.75 ms**, well under the **150 ms** threshold enforced by `test_import_boundary_scan_performance_under_150ms()`.

### Obs 3: Investigation of Flagged Layer 0 Imports in Pure Packages
1. **`addon/globalPlugins/AI-assistant/service/error_reporter.py:46`**:
   - Lines 44–48:
     ```python
     @staticmethod
     def _default_notify(message: str) -> None:
         try:
             from ..ui import nvda_ui
             nvda_ui.queue(nvda_ui.message, message)
     ```
   - `service/` is an inner pure layer; `ui/nvda_ui.py` is an outer Layer 0 adapter importing `queueHandler`, `ui`, `speech`, `tones`, and `logHandler`.
2. **`addon/globalPlugins/AI-assistant/use_case/focus_image.py:12`**:
   - Lines 12–13:
     ```python
     from ..image import capture_focused_object
     from ..image.services import ImageEncoder, ImagePreprocessor
     ```
   - When importing `use_case.focus_image` in an environment without `logHandler`:
     ```
     ModuleNotFoundError: No module named 'logHandler'
       File ".../use_case/focus_image.py", line 12, in <module>
         from ..image import capture_focused_object
       File ".../image/__init__.py", line 4, in <module>
         from .focus_capture import FocusCaptureResult, capture_focused_object
       File ".../image/focus_capture.py", line 11, in <module>
         from logHandler import log
     ```
   - Bypasses `ContextPipeline` despite `context/types.py:237` already defining `FocusedElementImageRequest`.
3. **`addon/globalPlugins/AI-assistant/service/error_presentation.py:71`**:
   - Line 71: `from ..image.screen_curtain import ScreenCurtainError` imports from Layer 0 `image` to reference an exception class.
4. **`addon/globalPlugins/AI-assistant/use_case/structure_summary.py:11`**:
   - Lines 11: `from ..context.navigation import build_llm_navigation_candidates`
   - Lines 1–554 of `context/navigation.py` are purely algorithmic (`NavigationTarget`, candidate selection).
   - Lines 555–676 contain live NVDA tree-interceptor navigation (`resolve_and_move_target`) importing `winUser` (line 610) and `textInfos` (line 635).
   - `resolve_and_move_target` is called only by `plugin/presenter.py:589`.

### Obs 4: `pyproject.toml` Banned-API Parity Gap
- In `tests/test_import_boundaries.py` lines 40–61, `FORBIDDEN_NVDA_MODULES` defines 18 host modules.
- In `pyproject.toml` lines 91–104, only 12 modules are listed under `[tool.ruff.lint.flake8-tidy-imports.banned-api]`.
- 6 modules are missing: `addonHandler`, `globalVars`, `winUser`, `locationHelper`, `treeInterceptorHandler`, `nvwave`.
- All legitimate call sites for these 6 modules are already inside Layer 0 directories covered by `[tool.ruff.lint.per-file-ignores]`. Adding them to `banned-api` produces 0 new lint errors on `uv run ruff check .`.

---

## 2. Logic Chain

1. **Pure Utils Inclusion**:
   - From Obs 1: `crypto.py`, `markdown.py`, and `mathml.py` are pure modules.
   - Requirement: Pure domain modules must be verified against NVDA import contamination.
   - Inference: Adding `PURE_UTILS_FILES = ("crypto.py", "markdown.py", "mathml.py")` to `tests/test_import_boundaries.py` with an automated assertion closes the testing gap without impacting the 150ms SLA.
2. **Watertight AST Scanner**:
   - From Obs 2: Scanner failed on 10/19 adversarial import variants because of `node.level == 0`, `node.module is None`, kwarg omissions, and byte pre-filtering.
   - From Obs 2: Parsing all 110 pure files with `ast.parse` directly takes only 60.75ms.
   - Inference: Removing the byte pre-filter and inspecting both module and alias names across `node.level >= 0` and keyword arguments resolves 100% of evasion vectors while comfortably beating the 150ms budget.
3. **Layer 0 Leaks Determination**:
   - From Obs 3.1: `service/error_reporter.py:46` imports `..ui.nvda_ui`. Hexagonal architecture strictly forbids domain services from importing outer UI delivery layers. Consequence: Must be eliminated via an injected notifier port (`register_error_notifier`).
   - From Obs 3.2: `use_case/focus_image.py:12` imports `..image`, which transitively imports `logHandler` and crashes pure standalone imports with `ModuleNotFoundError`. Consequence: Must be eliminated by routing focused image extraction through `ContextPipeline` via `FocusedElementImageRequest` (matching `use_case/image.py`).
   - From Obs 3.3: `service/error_presentation.py:71` imports `ScreenCurtainError` from `image`. Consequence: Move `ScreenCurtainError` to `core/errors.py` and re-export from `image/screen_curtain.py`.
   - From Obs 3.4: `use_case/structure_summary.py:11` imports pure algorithms from `context/navigation.py`. The pure algorithms are safe, but the presence of `resolve_and_move_target` in the same file forces `navigation.py` to be excluded from boundary scanning. Consequence: Move `resolve_and_move_target` to `plugin/browser_navigation.py`, allowing `context/navigation.py` to become a 100% pure file included in `PURE_CONTEXT_FILES`.
4. **Banned API Alignment**:
   - From Obs 4: The 6 missing modules are host modules that pure code must never import.
   - Adding them creates full parity with the AST test and ensures instant lint-time feedback via Ruff `TID251`.

---

## 3. Caveats

- `utils/__init__.py` currently imports `safe_read_clipboard` from `clipboard.py`. While `tests/test_import_boundaries.py` scans `crypto.py`, `markdown.py`, and `mathml.py` directly, any runtime test importing `utils.crypto` will trigger `utils/__init__.py`. Remediation of `utils/__init__.py` (via lazy export) is required for standalone execution.
- `context/navigation.py` contains 554 lines of pure algorithms and 122 lines of NVDA action code. If the implementer decides not to extract `resolve_and_move_target` to `plugin/` in this slice, `context/navigation.py` must remain in `per-file-ignores` and excluded from `PURE_CONTEXT_FILES`, although pure packages may safely continue importing `NavigationTarget` and `build_llm_navigation_candidates`.

---

## 4. Conclusion

A concrete, genuine fix strategy has been designed and documented in detail in `analysis.md`:
1. **`tests/test_import_boundaries.py`**:
   - Define `PURE_UTILS_FILES = ("crypto.py", "markdown.py", "mathml.py")` and add `test_pure_utils_modules_have_zero_forbidden_nvda_imports()`.
   - Fix `_find_forbidden_imports` to inspect all `ast.ImportFrom` nodes (`node.level >= 0`), check `node.names` when `node.module is None`, inspect dynamic import kwargs and functions, and remove the byte pre-filter.
   - Add `test_pure_packages_have_zero_layer0_adapter_imports()` to detect any relative imports into `ui`, `image`, or `plugin`.
2. **Decouple Flagged Layer 0 Imports**:
   - `service/error_reporter.py`: Replace `from ..ui import nvda_ui` with `register_error_notifier(notifier)`. Wire in `plugin/application.py`.
   - `use_case/focus_image.py`: Replace `from ..image import ...` with `extraction_intent=ExtractionIntent(requests=(FocusedElementImageRequest(),))` and consume image from pipeline context.
   - `service/error_presentation.py`: Move `ScreenCurtainError` to `core/errors.py`.
   - `context/navigation.py`: Extract `resolve_and_move_target` to `plugin/browser_navigation.py`; add `context/navigation.py` to `PURE_CONTEXT_FILES`.
3. **`pyproject.toml`**:
   - Add `addonHandler`, `globalVars`, `winUser`, `locationHelper`, `treeInterceptorHandler`, and `nvwave` to `[tool.ruff.lint.flake8-tidy-imports.banned-api]`.

---

## 5. Verification Method

1. **Verify AST Scanner Catches Relative & Evasive Imports**:
   ```powershell
   uv run python -c "from tests.test_import_boundaries import _find_forbidden_imports; import tempfile, pathlib; p = pathlib.Path(tempfile.gettempdir())/'test_rel.py'; p.write_text('from .. import api\nfrom ..api import getFocusObject\n'); print('Violations:', _find_forbidden_imports(p))"
   ```
   *Expected result*: Detects violations for both lines.
2. **Verify Pure Utils Boundary Scan**:
   ```powershell
   uv run pytest tests/test_import_boundaries.py -k "test_pure_utils"
   ```
   *Expected result*: 1 passed.
3. **Verify Ruff Banned APIs with New Rules**:
   ```powershell
   uv run ruff check .
   ```
   *Expected result*: 0 errors.
4. **Verify Ruff Flags Missing Modules**:
   ```powershell
   uv run ruff check --stdin-filename addon/globalPlugins/AI-assistant/core/test.py - <<< "import winUser; import globalVars"
   ```
   *Expected result*: 2 `TID251` errors reported.
5. **Verify Standalone Pure Import without NVDA**:
   ```powershell
   uv run python -c "import sys; sys.path = [p for p in sys.path if 'nvda' not in p.lower() or 'nvda-ai-assistant' in p.lower()]; from tests.support import load_addon_module; load_addon_module('use_case.focus_image', namespace='pure_test')"
   ```
   *Expected result*: Succeeds without `ModuleNotFoundError`.
