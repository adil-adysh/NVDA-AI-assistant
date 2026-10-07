# Handoff Report: Adversarial Verification of AST Boundary Tests & Ruff Banned API Enforcement

**Author**: Milestone 2 Challenger 2 (`m2_challenger_2_gen2`)  
**Scope**: Adversarial verification of AST Boundary Tests (`tests/test_import_boundaries.py`) & Ruff Banned API Enforcement (`pyproject.toml`) for Slice 0 & Slice 1  
**Target Milestone**: Milestone 2 (Slice 1 Pure Python Test Boundary Decoupling & Import Enforcement)  
**Verdict**: **`REQUEST_CHANGES`**

---

## 1. Observation

### 1.1 AST Scanner Evasion Matrix (`tests/test_import_boundaries.py`)
Direct inspection of `tests/test_import_boundaries.py`:
- Line 76:
  ```python
  raw_bytes = file_path.read_bytes()
  if not any(token in raw_bytes for token in FORBIDDEN_BYTES):
      return []
  ```
- Lines 90–94:
  ```python
  # From import statement: `from logHandler import log` (absolute only)
  elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
      root_pkg = node.module.partition(".")[0]
      if root_pkg in FORBIDDEN_NVDA_MODULES:
          violations.append((node.lineno, root_pkg, f"from {node.module} import ..."))
  ```
- Lines 97–115:
  ```python
  elif isinstance(node, ast.Call):
      if isinstance(node.func, ast.Name) and node.func.id == "__import__":
          if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
              root_pkg = node.args[0].value.partition(".")[0]
              if root_pkg in FORBIDDEN_NVDA_MODULES:
                  violations.append((node.lineno, root_pkg, f"__import__({node.args[0].value!r})"))
      elif (
          isinstance(node.func, ast.Attribute)
          and node.func.attr == "import_module"
          and node.args
          and isinstance(node.args[0], ast.Constant)
          and isinstance(node.args[0].value, str)
      ):
          root_pkg = node.args[0].value.partition(".")[0]
          if root_pkg in FORBIDDEN_NVDA_MODULES:
              violations.append(
                  (node.lineno, root_pkg, f"importlib.import_module({node.args[0].value!r})")
              )
  ```

An empirical stress harness running `_find_forbidden_imports` against 19 syntactic import variants yielded:

| Test Case | Import Syntax | AST Scanner Result | Status |
|---|---|---|---|
| 1 | `import api` | `[(1, 'api', 'import api')]` | DETECTED |
| 2 | `import api as my_api` | `[(1, 'api', 'import api')]` | DETECTED |
| 3 | `import speech.manager` | `[(1, 'speech', 'import speech.manager')]` | DETECTED |
| 4 | `import os, api, sys` | `[(1, 'api', 'import api')]` | DETECTED |
| 5 | `from api import getFocusObject` | `[(1, 'api', 'from api import ...')]` | DETECTED |
| 6 | `from speech.manager import speak` | `[(1, 'speech', 'from speech.manager import ...')]` | DETECTED |
| 7 | `from tones import beep as play_beep` | `[(1, 'tones', 'from tones import ...')]` | DETECTED |
| 8 | `from .api import getFocusObject` | `[]` | **MISSED (EVASION)** |
| 9 | `from ..api import getFocusObject` | `[]` | **MISSED (EVASION)** |
| 10 | `from .. import api` | `[]` | **MISSED (EVASION)** |
| 11 | `from . import api` | `[]` | **MISSED (EVASION)** |
| 12 | `x = __import__('api')` | `[(1, 'api', "__import__('api')")]` | DETECTED |
| 13 | `x = __import__(name='api')` | `[]` | **MISSED (EVASION)** |
| 14 | `x = builtins.__import__('api')` | `[]` | **MISSED (EVASION)** |
| 15 | `x = importlib.import_module('api')` | `[(1, 'api', "importlib.import_module('api')")]` | DETECTED |
| 16 | `x = importlib.import_module(name='api')` | `[]` | **MISSED (EVASION)** |
| 17 | `from importlib import import_module; x = import_module('api')` | `[]` | **MISSED (EVASION)** |
| 18 | `import \u0061pi` | `[]` | **MISSED (EVASION)** |
| 19 | `x = __import__("\x61pi")` | `[]` | **MISSED (EVASION)** |

Out of 19 test cases, **10 bypasses succeeded**. In particular, **100% of relative import forms were completely missed** because line 91 explicitly requires `node.level == 0 and node.module`.

---

### 1.2 Active Layer 0 Adapter Leaks in Pure Packages in HEAD
Because `tests/test_import_boundaries.py` ignores all relative imports (`node.level > 0`), the following Layer 0 adapter imports are actively present in production pure packages and passed the test suite with 0 errors:

1. **`addon/globalPlugins/AI-assistant/service/error_reporter.py:46`**:
   ```python
   44: 	def _default_notify(message: str) -> None:
   45: 		try:
   46: 			from ..ui import nvda_ui
   47: 
   48: 			nvda_ui.queue(nvda_ui.message, message)
   ```
   `service/` is designated a pure package in `PURE_DIRECTORIES`. `ui/nvda_ui.py` is a Layer 0 adapter importing `api`, `speech`, `tones`, `queueHandler`, and `wx`.

2. **`addon/globalPlugins/AI-assistant/use_case/focus_image.py:12-13`**:
   ```python
   12: from ..image import capture_focused_object
   13: from ..image.services import ImageEncoder, ImagePreprocessor
   ```
   `use_case/` is a pure package. `image/` is a Layer 0 adapter whose `image/focus_capture.py` and `image/screen_curtain.py` import `logHandler`, `screenCurtain`, and `PIL.ImageGrab`.

3. **`addon/globalPlugins/AI-assistant/use_case/structure_summary.py:11` & `structure_summary_response.py:9`**:
   ```python
   11: from ..context.navigation import build_llm_navigation_candidates
   ```
   `context/navigation.py` was deliberately excluded from `PURE_CONTEXT_FILES` and excluded from Ruff `TID251` (`pyproject.toml:119`) because lines 610 & 635 import `winUser` and `textInfos`. Yet pure `use_case/` imports directly from `context/navigation.py`.

---

### 1.3 Transitive `logHandler` Contamination Breaking Standalone Imports
In `PROJECT.md` §Features:
> Feature 15: Standalone Pure Test Execution — Verify pure tests execute in < 3s with `uv run pytest -m "not nvda_integration"` without `../nvda`.

When executing standalone import of `config.settings` in clean Python without NVDA on `sys.path`:
```powershell
python -c "
import sys
sys.path = [p for p in sys.path if 'nvda' not in p.lower() or 'nvda-ai-assistant' in p.lower()]
from tests.support import load_addon_module
load_addon_module('config.settings')
"
```
**Verbatim Output**:
```
config.settings failed to load: No module named 'logHandler'
```

**Traceback Root Cause**:
1. `config/settings.py` imports `config/yaml_store.py:12`:
   `from ..utils.crypto import decrypt_value, encrypt_value, is_encrypted, is_sensitive_key`
2. Python executes package initialization `addon/globalPlugins/AI-assistant/utils/__init__.py:4`:
   `from .clipboard import safe_read_clipboard`
3. `addon/globalPlugins/AI-assistant/utils/clipboard.py:11` executes:
   `from logHandler import log`
4. `logHandler` does not exist outside NVDA, causing an immediate `ModuleNotFoundError`.
Because `utils/` is not in `PURE_DIRECTORIES`, this contamination was invisible to `tests/test_import_boundaries.py`.

---

### 1.4 Ruff `TID251` Verification in `pyproject.toml`
An empirical matrix of 108 direct imports (`import <api>`) and 108 from-imports (`from <api> import dummy`) was executed across all 9 pure packages (`core`, `config`, `service`, `providers`, `use_case`, `prompts`, `tools`, `observability`, `embeddings`) against `uv run ruff check --stdin-filename ...`:
- Result for the 12 configured banned APIs: **216/216 triggered TID251**.
- **However, 6 forbidden host modules defined in `tests/test_import_boundaries.py` are MISSING from `pyproject.toml`**:
  `addonHandler`, `globalVars`, `winUser`, `locationHelper`, `treeInterceptorHandler`, `nvwave`.
- Testing confirmed that importing any of these 6 modules into pure packages yields **0 TID251 errors** from Ruff:
  ```
  addonHandler              -> TID251=False
  globalVars                -> TID251=False
  winUser                   -> TID251=False
  locationHelper            -> TID251=False
  treeInterceptorHandler    -> TID251=False
  nvwave                    -> TID251=False
  ```
- Furthermore, Ruff TID251 does not catch relative imports (`from .api import x` or `from .. import api` both yield `TID251=False`).

---

## 2. Logic Chain

1. **Premise 1 (Boundary Specification)**: Slice 1 requirements in `ORIGINAL_REQUEST.md §R2` and `PROJECT.md` mandate that pure packages (`core/`, `config/`, `service/`, `providers/`, `use_case/`, etc.) must never directly or transitively import forbidden NVDA modules, and must be able to load and execute without an NVDA checkout.
2. **Premise 2 (Scanner Defense Capability)**: Task 1 requires verifying whether the AST scanner correctly detects all forms of forbidden imports, specifically citing relative imports that resolve to forbidden modules.
3. **Inference from Obs 1.1**: `tests/test_import_boundaries.py` line 91 contains `and node.level == 0 and node.module`. This condition systematically suppresses violation reporting on all relative imports.
4. **Inference from Obs 1.2**: Because relative imports are suppressed and `ui`, `image`, and `context.navigation` are omitted from boundary rules, `service/error_reporter.py:46`, `use_case/focus_image.py:12`, and `use_case/structure_summary.py:11` leak Layer 0 NVDA adapter surfaces into pure packages undetected.
5. **Inference from Obs 1.3**: Eager import of `clipboard.py` inside `utils/__init__.py` causes any pure module importing `utils.crypto` or `utils.markdown` to transitively load `logHandler` and `api`, failing standalone execution when NVDA is absent.
6. **Inference from Obs 1.4**: `pyproject.toml` TID251 configuration is incomplete, omitting 6 host modules (`addonHandler`, `globalVars`, `winUser`, `locationHelper`, `treeInterceptorHandler`, `nvwave`), creating an asymmetric gap where Ruff permits imports that the AST test forbids.
7. **Deductive Conclusion**: Slice 1 import boundary enforcement contains critical evasion holes and real dependency contamination that violate Invariant A5 and the standalone test execution requirement.

---

## 3. Caveats

- `uv run pytest tests/test_import_boundaries.py` currently passes with 3/3 passing tests because the AST test is blind to the existing leaks, and `tests/test_import_boundaries.py` does not attempt to import the actual add-on modules.
- The full test suite (`uv run pytest`) passes 450 tests only because `conftest.py` lines 86–94 inject `logHandler`, `controlTypes`, and `textInfos` into `sys.modules` from the sibling `../nvda` checkout when `HAS_NVDA_CHECKOUT` is true.

---

## 4. Conclusion & Required Changes

**VERDICT**: **`REQUEST_CHANGES`**

### Required Changes:
1. **Fix `tests/test_import_boundaries.py` relative import inspection**:
   - For `ast.ImportFrom`:
     - If `node.module`: inspect `node.module.partition(".")[0]` regardless of `node.level` (e.g. `from ..api import ...`).
     - If `node.module is None` (e.g. `from .. import api`): iterate `node.names` and check `alias.name in FORBIDDEN_NVDA_MODULES`.
     - In pure packages, forbid relative imports into Layer 0 packages (`ui`, `image`, `plugin`, `context.extractors`, `context.navigation`).
   - Remove or fix the `FORBIDDEN_BYTES` pre-filter to handle unicode/hex escape decoding before token scanning, or parse AST directly.
   - Detect dynamic imports with keyword arguments (`name=...`) and direct function calls `import_module(...)`.
2. **Decouple `utils/__init__.py`**:
   - Remove `from .clipboard import safe_read_clipboard` from `utils/__init__.py`. Make clipboard exports lazy (e.g., via `__getattr__`) or move `clipboard.py` to an adapter location (`ui/` or Layer 0), preventing `utils.crypto` from triggering `logHandler`.
3. **Decouple `service/error_reporter.py`**:
   - Remove `from ..ui import nvda_ui` at line 46. The default notifier should accept an injected notification callback rather than importing Layer 0 UI adapter directly.
4. **Decouple `use_case/focus_image.py` & `use_case/structure_summary.py`**:
   - Inject image capture and navigation resolution via ports/protocols rather than importing `..image` and `..context.navigation`.
5. **Align `pyproject.toml` `banned-api`**:
   - Add the 6 missing host modules to `[tool.ruff.lint.flake8-tidy-imports.banned-api]`:
     `addonHandler`, `globalVars`, `winUser`, `locationHelper`, `treeInterceptorHandler`, `nvwave`.

---

## 5. Verification Method

To independently verify all reported findings:

1. **Verify AST Scanner Relative Import Evasion**:
   ```powershell
   python -c "from tests.test_import_boundaries import _find_forbidden_imports; import tempfile, pathlib; p = pathlib.Path(tempfile.gettempdir())/'test_rel.py'; p.write_text('from .. import api\nfrom ..api import getFocusObject\n'); print('Violations:', _find_forbidden_imports(p))"
   ```
   *Expected result*: `Violations: []` (bypassed).

2. **Verify Transitive Standalone Import Failure without NVDA**:
   ```powershell
   python -c "import sys; sys.path = [p for p in sys.path if 'nvda' not in p.lower() or 'nvda-ai-assistant' in p.lower()]; from tests.support import load_addon_module; load_addon_module('config.settings')"
   ```
   *Expected result*: `ModuleNotFoundError: No module named 'logHandler'`.

3. **Verify Active Layer 0 Imports in Pure Packages**:
   ```powershell
   git grep -n "from \.\.ui" addon/globalPlugins/AI-assistant/service/
   git grep -n "from \.\.image" addon/globalPlugins/AI-assistant/use_case/
   git grep -n "from \.\.context\.navigation" addon/globalPlugins/AI-assistant/use_case/
   ```

4. **Verify Missing Ruff TID251 Rules**:
   ```powershell
   uv run ruff check --stdin-filename addon/globalPlugins/AI-assistant/core/test.py - <<< "import winUser; import globalVars"
   ```
   *Expected result*: 0 TID251 errors.
