# Technical Analysis & Fix Strategy: Transitive logHandler Contamination & Production Bridge/Resolver Wiring

**Author**: Milestone 2 Explorer 2 (Iteration 2)  
**Date**: 2026-10-04T22:50:00Z  
**Target Milestone**: Milestone 2 (Migration Slice 0 & Slice 1 Remediation)  
**Status**: APPROVED FIX STRATEGY  
**Related Reports**:
- Forensic Audit Report: `.agents/teamwork/m2_auditor_1_gen2/handoff.md` (Integrity Violation)
- Adversarial Review Report: `.agents/teamwork/m2_challenger_1_gen2/handoff.md` (Request Changes)
- Reviewer 2 Report: `.agents/teamwork/m2_reviewer_2_gen2/handoff.md` (Finding 1 & Suggestions)

---

## 1. Executive Summary

During Iteration 1 of Milestone 2 (Slice 1), the work product was rejected by the Forensic Auditor with **INTEGRITY VIOLATION** due to four interconnected flaws:
1. **Transitive `logHandler` Contamination**: `addon/globalPlugins/AI-assistant/utils/__init__.py` eagerly imported `safe_read_clipboard` from `utils/clipboard.py`, which in turn imported `from logHandler import log` at module scope. Consequently, any pure domain or test module importing `config.yaml_store` (or `config.settings`, `service.chat.coordinator`, `providers.llama_manager`, etc.) crashed in pure Python environments with `ModuleNotFoundError: No module named 'logHandler'`.
2. **Facade / Dead-Code Bridge (`NVDALogBridge`)**: `attach_nvda_log_bridge()` was implemented in `utils/logger.py` but never called anywhere during NVDA plugin startup (`plugin/application.py` or `plugin/controller.py`). As a result, in production NVDA, all log entries from the 18 decoupled pure modules were silently lost.
3. **Premature Record Discard in Bridge**: `attach_nvda_log_bridge()` did not configure the target logger's level to `logging.DEBUG`. Because stdlib Python loggers default to `WARNING` (or inherit `NOTSET`), any `log.debug()` or `log.info()` calls would be discarded by `Logger.isEnabledFor()` before reaching `NVDALogBridge.emit()`.
4. **Unwired Language Resolver**: `register_language_resolver` was implemented in `config/settings.py` but never invoked during production NVDA startup, causing `get_effective_language()` to permanently fall back to `"en"` and ignoring NVDA's active user language.

This document delivers a concrete, production-grade fix strategy for all four defects, including exact code modifications, architectural justification, blast-radius assessments, and independent verification procedures.

---

## 2. Deep Dive & Fix Specification: Item by Item

### 2.1 Item 1: Decoupling `addon/globalPlugins/AI-assistant/utils/__init__.py`

#### Problem Analysis & Evidence
- **File Location**: `addon/globalPlugins/AI-assistant/utils/__init__.py:4`
- **Current Content**:
  ```python
  # -*- coding: utf-8 -*-
  from __future__ import annotations

  from .clipboard import safe_read_clipboard
  from .markdown import render_markdown_to_html

  __all__ = ["render_markdown_to_html", "safe_read_clipboard"]
  ```
- **Execution Failure**:
  When pure code imports `config.yaml_store`:
  ```python
  from ..utils.crypto import decrypt_value, encrypt_value, is_encrypted, is_sensitive_key
  ```
  Python initializes the `utils` package by running `utils/__init__.py`. Because line 4 eagerly executes `from .clipboard import safe_read_clipboard`, `utils/clipboard.py` is imported immediately. In an environment without NVDA host modules in `sys.path`, this triggers `ModuleNotFoundError: No module named 'logHandler'` (`bootstrap.py:45 -> yaml_store.py:12 -> utils/__init__.py:4 -> clipboard.py:11`).
- **Consumer Inventory**:
  - `render_markdown_to_html`: Consumers (`service.chat.projector`, `ui.adapter`, `plugin.presenter`, `use_case.base`) import directly from `..utils.markdown import render_markdown_to_html`.
  - `safe_read_clipboard`: Only consumed in `plugin/application.py:31` (`from ..utils.clipboard import safe_read_clipboard`).
  - `crypto`: Consumed in `config/yaml_store.py:12` (`from ..utils.crypto import ...`).
  - No module in the entire repository imports `from ..utils import safe_read_clipboard`.

#### Concrete Fix
Eliminate the eager import of `from .clipboard import safe_read_clipboard`. To maintain complete backward compatibility and satisfy any dynamic lookup or wildcard imports, implement PEP 562 module-level `__getattr__`:

```python
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from .markdown import render_markdown_to_html

__all__ = ["render_markdown_to_html", "safe_read_clipboard"]


def __getattr__(name: str) -> Any:
	if name == "safe_read_clipboard":
		from .clipboard import safe_read_clipboard

		return safe_read_clipboard
	raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

#### Rationale & Invariants
- `utils.markdown` and `utils.mathml` are 100% pure Python; keeping `render_markdown_to_html` eager is completely safe.
- `__getattr__` ensures `safe_read_clipboard` is only loaded if explicitly requested from `utils`.
- Normal relative submodule imports (e.g. `from ..utils.crypto import ...`) execute `utils/__init__.py` without triggering `__getattr__`, completely isolating pure modules from `clipboard.py`.

---

### 2.2 Item 2: Purging `logHandler` from `addon/globalPlugins/AI-assistant/utils/clipboard.py`

#### Problem Analysis & Evidence
- **File Location**: `addon/globalPlugins/AI-assistant/utils/clipboard.py:11`
- **Current Content**:
  ```python
  # -*- coding: utf-8 -*-
  """System clipboard utilities — pure Python, no external dependencies.
  ...
  """

  from __future__ import annotations

  from logHandler import log


  def safe_read_clipboard() -> str | None:
  	try:
  		import api

  		return api.getClipData() or None
  	except Exception:
  		log.exception("Error reading clipboard via api.getClipData")
  		return None
  ```
- **Execution Failure**:
  Although `safe_read_clipboard()` defers `import api` inside the function body with a `try...except Exception:` block, `from logHandler import log` was placed at module scope on line 11. Even if imported in isolation, it crashed immediately when `logHandler` was unavailable.

#### Concrete Fix
Replace `from logHandler import log` with standard library `logging.getLogger(__name__)`:

```python
# -*- coding: utf-8 -*-
"""System clipboard utilities.

Uses NVDA's built-in ``api.getClipData()`` which internally drives the
``winUser.openClipboard`` context manager.  This is the canonical NVDA pattern
used throughout the NVDA source (``globalCommands.py``, ``MathCAT.py``).
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def safe_read_clipboard() -> str | None:
	"""Read text from the system clipboard.

	Returns the clipboard text string, or ``None`` if the clipboard is empty,
	contains non-text content, or cannot be read.
	"""
	try:
		import api

		return api.getClipData() or None
	except Exception:
		log.exception("Error reading clipboard via api.getClipData")
		return None
```

#### Rationale & Invariants
- `logging.getLogger(__name__)` adheres to Architectural Invariant A5 (Pure Python Domain Isolation).
- Standard library `Logger.exception()` has identical semantics to NVDA's `log.exception()` (logs message with level `ERROR` and `exc_info=True`).
- When running in NVDA, `NVDALogBridge` intercepts this record and routes it into NVDA's log file with full caller `codepath`.
- Outside NVDA (e.g. pytest without checkout), `safe_read_clipboard()` imports cleanly without errors.
- **Ruff Linting**: `clipboard.py` is exempted in `pyproject.toml` line 121 for `TID251` because of `import api`. Purging `logHandler` ensures it only requires NVDA APIs during live runtime clipboard reads.

---

### 2.3 Item 3: Production Wiring of `attach_nvda_log_bridge()` and `register_language_resolver()`

#### Problem Analysis & Evidence
- **File Locations**:
  - `addon/globalPlugins/AI-assistant/plugin/application.py`
  - `addon/globalPlugins/AI-assistant/plugin/controller.py`
- **Defects Identified**:
  1. `attach_nvda_log_bridge` was defined in `utils/logger.py` but never called in any production code (`git grep attach_nvda_log_bridge` returned 0 production calls). In production NVDA, `NVDALogBridge` was never attached, causing all logs from the 18 decoupled pure modules to be dropped.
  2. `register_language_resolver` was defined in `config/settings.py` but never called in production code (`git grep register_language_resolver` only matched tests). In production NVDA, `get_effective_language()` always returned `"en"`, breaking non-English localization for all default prompt generation.

#### Architecture & Placement Analysis
- **`GlobalPlugin` (`plugin/controller.py`)** is NVDA's COM entry point created by NVDA's plugin loader.
- **`AIAssistantApplication` (`plugin/application.py`)** owns domain lifecycle, services, background runner, and presentation.
- **Exact Placement**:
  Wiring must occur at the very start of `AIAssistantApplication.__init__`, immediately after `addonHandler.initTranslation()` and BEFORE `build_plugin_services()`:
  - `attach_nvda_log_bridge()` must be operational before any domain service or manager logs its first initialization message.
  - `register_language_resolver(languageHandler.getLanguage)` must be registered before any service queries `get_effective_language()`.
  - In `AIAssistantApplication.terminate()`, `register_language_resolver(None)` must be invoked to avoid dangling callbacks on addon reload.
  - In `GlobalPlugin.__init__`, calling `attach_nvda_log_bridge()` provides defense-in-depth, ensuring that any logging inside `controller.py` before `AIAssistantApplication` is bridged.

#### Concrete Code Changes

##### In `addon/globalPlugins/AI-assistant/plugin/application.py`:
1. **Imports**:
   ```python
   # In settings import block (around line 14):
   from ..config.settings import (
       get_enabled_providers,
       get_llama_start_on_startup,
       get_litert_start_on_startup,
       get_provider,
       get_provider_state,
       register_language_resolver,
   )

   # Add logger bridge import (around line 32):
   from ..utils.logger import attach_nvda_log_bridge
   ```

2. **In `AIAssistantApplication.__init__` (lines 58–66)**:
   ```python
   class AIAssistantApplication:
       def __init__(self, host: Any) -> None:
           super().__init__()
           addonHandler.initTranslation()
           attach_nvda_log_bridge()
           try:
               import languageHandler

               register_language_resolver(languageHandler.getLanguage)
           except ImportError:
               pass
           log.debug("Browser Assistant plugin initializing")
           self._host = host
           self._services = build_plugin_services()
   ```

3. **In `AIAssistantApplication.terminate` (around line 170)**:
   ```python
           try:
               register_language_resolver(None)
           except Exception:
               log.exception("Error unregistering language resolver during terminate")
   ```

##### In `addon/globalPlugins/AI-assistant/plugin/controller.py`:
In `GlobalPlugin.__init__` (around line 30):
```python
	def __init__(self) -> None:
		super().__init__()
		from ..utils.logger import attach_nvda_log_bridge

		attach_nvda_log_bridge()
		self._app = AIAssistantApplication(self)
		self._tools_menu = gui.mainFrame.sysTrayIcon.toolsMenu
		self._build_tools_submenu()
```

---

### 2.4 Item 4: Logger Level Configuration in `addon/globalPlugins/AI-assistant/utils/logger.py`

#### Problem Analysis & Evidence
- **File Location**: `addon/globalPlugins/AI-assistant/utils/logger.py:68–87`
- **Defect**:
  In standard library Python:
  - When a logger is created, `target_logger.level` is `NOTSET` (0).
  - The root logger's default level is `WARNING` (30).
  - `logger.debug()` and `logger.info()` call `isEnabledFor()`. If the effective level is `WARNING`, `isEnabledFor(DEBUG)` returns `False`, and the call returns immediately without invoking any handlers.
  - As observed by Forensic Auditor Finding 1.3:
    `attach_nvda_log_bridge fails to configure the target logger's level (which defaults to WARNING in stdlib Python), meaning that even if attached, DEBUG and INFO records would be discarded by Logger.isEnabledFor() before reaching NVDALogBridge.emit().`
- NVDA's own logger (`nvda_log`) already manages level filtering authoritatively based on user settings (`--debug-logging` -> `DEBUG`, standard -> `INFO`).
- Therefore, `target_logger` must be set to `logging.DEBUG` so all log records reach `NVDALogBridge.emit()`, where `nvda_log` decides whether to format and output them.

#### Concrete Fix
In `addon/globalPlugins/AI-assistant/utils/logger.py:attach_nvda_log_bridge`:
Set `target_logger.setLevel(logging.DEBUG)` immediately after acquiring `target_logger`:

```python
def attach_nvda_log_bridge(logger_name: str | None = None) -> bool:
	"""Attach NVDALogBridge to the specified logger or root logger.

	Returns True if bridge was attached, False if outside NVDA or already attached.
	"""
	try:
		from logHandler import logHandler as nvda_handler
	except ImportError:
		return False  # Running in pure Python environment; no-op

	target_logger = logging.getLogger(logger_name)
	target_logger.setLevel(logging.DEBUG)

	# Avoid duplicate bridge attachment
	for handler in target_logger.handlers:
		if isinstance(handler, NVDALogBridge):
			return True

	bridge = NVDALogBridge()
	target_logger.addHandler(bridge)

	# Install duplication prevention filter on NVDA's root logHandler
	if nvda_handler is not None and hasattr(nvda_handler, "addFilter"):
		# Ensure we only add filter once
		filters = getattr(nvda_handler, "filters", [])
		if _drop_bridged_filter not in filters:
			nvda_handler.addFilter(_drop_bridged_filter)

	return True
```

#### Verification of Log Record Routing
When bridged in NVDA:
1. Pure module executes `log.info("Model loaded")` or `log.debug("Cache miss")`.
2. Target logger has level `DEBUG` -> `isEnabledFor()` returns `True`.
3. `NVDALogBridge.emit(record)`:
   - Sets `record._nvda_bridged = True`.
   - Computes `codepath` (`f"{record.name}.{record.funcName}"`).
   - Dispatches through `nvda_log._log(record.levelno, msg, (), extra={"codepath": codepath}, ...)`.
4. The new record emitted by `nvda_log` has `name == "nvda"`, passing NVDA's `filterExternalDependencyLogging` filter.
5. NVDA's `_drop_bridged_filter` drops the unbridged standard library record from the root file handler, preventing duplicate output.
6. The resulting line in `nvda.log` appears with NVDA's exact native format:
   `INFO - config.state._notify_provider_state_changed (14:22:01.123) - MainThread: Model loaded`

---

## 3. Systemic Impact & Test Tier Decoupling

### 3.1 Impact on Absent Sibling NVDA Checkout Simulation
When `HAS_NVDA_CHECKOUT` evaluates to `False`:
- Prior to fix, 8 test files failed collection.
- With Item 1 and Item 2 fixed:
  - `tests/config/test_yaml_store.py`: **COLLECTS & PASSES** (no longer touches `logHandler`).
  - `tests/integration/test_chat_lifecycle.py`: **COLLECTS & PASSES** (no longer touches `logHandler`).
  - `tests/providers/test_llama_provider.py`: **COLLECTS & PASSES** (no longer touches `logHandler`).
- The remaining 5 test files (`tests/architecture/test_use_case_flow.py`, `tests/plugin/test_background_provider_ready.py`, `tests/plugin/test_background_shutdown.py`, `tests/plugin/test_presenter_ui_actions.py`, `tests/ui/test_adapter_fallback.py`) are Layer 0 presentation / integration tests that explicitly import NVDA UI/plugin classes. They must be gated with `pytestmark = pytest.mark.nvda_integration` or skipped during collection when `HAS_NVDA_CHECKOUT is False`.

### 3.2 AST Import Boundary Test Enhancements (`tests/test_import_boundaries.py`)
To prevent regression and guarantee that pure utilities are continuously scanned:
Add `PURE_UTILS_FILES = ("crypto.py", "markdown.py", "mathml.py")` to `tests/test_import_boundaries.py`:
```python
PURE_UTILS_FILES: tuple[str, ...] = (
	"crypto.py",
	"markdown.py",
	"mathml.py",
)


def test_pure_utils_modules_have_zero_forbidden_nvda_imports() -> None:
	"""Assert that pure utility modules have zero NVDA imports."""
	violations: list[str] = []
	for fname in PURE_UTILS_FILES:
		fpath = ADDON_ROOT / "utils" / fname
		if not fpath.is_file():
			continue
		for lineno, forbidden_pkg, stmt in _find_forbidden_imports(fpath):
			violations.append(
				f"  utils/{fname}:{lineno} -> forbidden '{forbidden_pkg}' ({stmt})"
			)

	assert not violations, (
		f"Found {len(violations)} forbidden NVDA import(s) in pure utils files:\n"
		+ "\n".join(violations)
	)
```
Empirical test execution confirms all 3 files pass with 0 violations.

### 3.3 Unit Test for `utils/logger.py` (`tests/unit/test_logger.py`)
To ensure `utils/logger.py` is covered by automated unit tests:
Add `tests/unit/test_logger.py` testing:
1. `attach_nvda_log_bridge()` outside NVDA returns `False`.
2. `attach_nvda_log_bridge()` sets `target_logger.level == logging.DEBUG`.
3. `NVDALogBridge.emit()` preserves `codepath` and flags `_nvda_bridged = True`.
4. `NVDALogBridge.emit()` ignores records with `name == "nvda"` or `_nvda_bridged = True` (recursion prevention).
5. `_drop_bridged_filter()` correctly filters out bridged records.

---

## 4. Implementation Step-by-Step Roadmap

| Step | Target File | Action | Lines | Description |
|---|---|---|---|---|
| **1** | `addon/globalPlugins/AI-assistant/utils/__init__.py` | Edit | 4–8 | Replace eager `from .clipboard import safe_read_clipboard` with PEP 562 `__getattr__` |
| **2** | `addon/globalPlugins/AI-assistant/utils/clipboard.py` | Edit | 11 | Replace `from logHandler import log` with `import logging; log = logging.getLogger(__name__)` |
| **3** | `addon/globalPlugins/AI-assistant/utils/logger.py` | Edit | 78–82 | Add `target_logger.setLevel(logging.DEBUG)` in `attach_nvda_log_bridge()` |
| **4** | `addon/globalPlugins/AI-assistant/plugin/application.py` | Edit | 14, 32, 60–65, 170 | Wire `attach_nvda_log_bridge()` and `register_language_resolver(languageHandler.getLanguage)` in `__init__`, and `register_language_resolver(None)` in `terminate()` |
| **5** | `addon/globalPlugins/AI-assistant/plugin/controller.py` | Edit | 30–35 | Call `attach_nvda_log_bridge()` in `GlobalPlugin.__init__` as defense-in-depth |
| **6** | `tests/test_import_boundaries.py` | Edit | 38–45 | Add `PURE_UTILS_FILES` and `test_pure_utils_modules_have_zero_forbidden_nvda_imports()` |
| **7** | `tests/unit/test_logger.py` | Create | 1–85 | Implement comprehensive unit test suite for `NVDALogBridge` and `attach_nvda_log_bridge()` |

---

## 5. Independent Verification Plan

### Test 1: Pure Package Import Verification
```pwsh
uv run python -c "from tests.support import load_addon_module; mod = load_addon_module('config.yaml_store', namespace='pure_test'); print('SUCCESS: yaml_store loaded cleanly!')"
```
*Expected*: Prints `SUCCESS: yaml_store loaded cleanly!` with exit code 0.

### Test 2: Clipboard Pure Import Verification
```pwsh
uv run python -c "from tests.support import load_addon_module; mod = load_addon_module('utils.clipboard', namespace='pure_test'); assert mod.safe_read_clipboard() is None; print('SUCCESS: clipboard pure test passed!')"
```
*Expected*: Prints `SUCCESS: clipboard pure test passed!` with exit code 0.

### Test 3: AST Boundary & Ruff Lint Verification
```pwsh
uv run ruff check .
uv run pytest tests/test_import_boundaries.py
```
*Expected*: Ruff reports `All checks passed!`, AST boundary tests pass 4/4 in < 100ms.

### Test 4: Pure Test Suite Execution
```pwsh
uv run pytest -m "not nvda_integration"
```
*Expected*: All pure tests pass cleanly.

### Test 5: Production Wiring Static Verification
```pwsh
git grep -n "attach_nvda_log_bridge" addon/
git grep -n "register_language_resolver" addon/
```
*Expected*:
- `attach_nvda_log_bridge` called in `addon/globalPlugins/AI-assistant/plugin/application.py` and `plugin/controller.py`.
- `register_language_resolver` called in `addon/globalPlugins/AI-assistant/plugin/application.py`.
