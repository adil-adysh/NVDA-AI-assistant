# Slice 1 Investigation & Technical Design: Pure Python Logging & Language Decoupling

**Author:** Explorer 2 (Milestone 2, Slice 1)  
**Date:** 2026-10-04  
**Target Commit:** `ced1cbc` (HEAD)  
**Working Directory:** `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m2_explorer_2`  
**Artifacts:** `analysis.md`, `handoff.md`  

---

## Executive Summary

This document presents the detailed architectural design and exact file-by-file replacement specifications for **Milestone 2 (Slice 1: Pure Python Test Boundary Decoupling)**, focusing on:
1. **The Logging Facade & Bridge (`utils/logger.py`)**: Designing `NVDALogBridge(logging.Handler)` that transparently bridges standard library logging (`logging.getLogger(__name__)`) used in pure packages into NVDA's authoritative `logHandler.log`, ensuring NVDA's `filterExternalDependencyLogging` (`record.name == "nvda"`) passes `DEBUG` and `INFO` records, preventing recursion, preserving caller `codepath` context, and avoiding duplicate messages.
2. **The 18-File Pure Package Logging Purge**: Formulating exact before-and-after code specifications for all 18 pure domain/service/config/provider modules that currently import `from logHandler import log`.
3. **Language Resolver Decoupling in `config/settings.py`**: Designing the `register_language_resolver(resolver: Callable[[], str] | None)` port, eliminating the top-level `import languageHandler` at line 8, providing resilient fallback to `"en"`, and detailing the host wiring in the plugin layer.

---

## 1. Deep Dive: NVDA Logging Mechanics & Filter Discovery

### 1.1 NVDA's Logging Architecture (`logHandler.py`)
In NVDA core (`D:\nvda-addons\nvda\source\logHandler.py`), logging is initialized via `initialize()`:
- `NVDA_LOGGER_NAME = "nvda"` (line 524)
- `log: Logger = logging.getLogger(NVDA_LOGGER_NAME)` (line 528)
- NVDA's `FileHandler` (or `RemoteHandler`) is attached to `log.root` (`logging.root`, line 673).
- NVDA's `logFormatter` (lines 631–634) uses the format:
  ```python
  fmt="{levelname!s} - {codepath!s} ({asctime}) - {threadName} ({thread}):\n{message}"
  ```
  Crucially, this formatter requires every log record to possess a `codepath` attribute. In NVDA's `Logger._log` (lines 266–271):
  ```python
  if not codepath:
      codepath = getCodePath(f)
  extra["codepath"] = codepath
  ```

### 1.2 The `filterExternalDependencyLogging` Trap
In `logHandler.py` lines 605–612:
```python
def filterExternalDependencyLogging(record: logging.LogRecord) -> bool:
    import config
    return (
        record.name == NVDA_LOGGER_NAME
        or record.levelno >= Logger.WARNING
        or config.conf["debugLog"]["externalPythonDependencies"]
    )
```
Where `NVDA_LOGGER_NAME = "nvda"`.
This filter is attached to NVDA's `logHandler` on `log.root` (line 672).

**Key Discovery & Operational Impact:**
If pure Python add-on modules use standard library `logging.getLogger(__name__)`:
1. `record.name` will be the Python module path (e.g. `addon.globalPlugins.AI-assistant.config.state` or `config.state`).
2. When this record reaches `log.root`, `filterExternalDependencyLogging` evaluates:
   - `record.name == "nvda"` is `False`.
   - If `record.levelno < Logger.WARNING` (i.e. `DEBUG` or `INFO`), and `externalPythonDependencies` is not enabled in the user's NVDA config, the record is **silently dropped**.
3. Therefore, simply switching pure modules to `logging.getLogger(__name__)` without an NVDA bridge would cause all production `DEBUG` and `INFO` logs from the add-on's pure domain/service layer to vanish in NVDA!
4. Furthermore, if a naive bridge catches records on `log.root` and re-dispatches them to `logHandler.log`, two severe risks emerge:
   - **Infinite Recursion:** `logHandler.log` creates a record with `record.name == "nvda"` which bubbles back to `log.root`. If the bridge handles it again, a recursive loop occurs.
   - **Duplicate Messages:** For `WARNING` and `ERROR`, NVDA's root handler passes both the original record (`record.levelno >= WARNING`) and the bridged record (`record.name == "nvda"`), resulting in double log entries in `nvda.log`.

---

## 2. Design Specification: `addon/globalPlugins/AI-assistant/utils/logger.py`

### 2.1 Architectural Invariants
1. **Pure Environment Safety:** `utils/logger.py` MUST NOT import `logHandler` at module top-level. When running outside NVDA (e.g. in standalone pure pytest or a worker process), `import addon.globalPlugins.AI-assistant.utils.logger` must succeed without `ModuleNotFoundError`.
2. **Standard Library Purity in Pure Packages:** Pure packages never import `logHandler`, nor do they strictly require `utils.logger`. They simply call:
   ```python
   import logging

   log = logging.getLogger(__name__)
   ```
3. **Monotonic Name Preservation:** When `NVDALogBridge` intercepts a record, it routes it through `logHandler.log._log(...)` so that the newly created record possesses `record.name == "nvda"`.
4. **Accurate Caller Context (`codepath`):** `NVDALogBridge` computes `codepath` from the original `record.name` and `record.funcName` (e.g. `config.state._notify_provider_state_changed`) and passes it explicitly to `_log(..., codepath=codepath)`. This prevents the log formatter from reporting `NVDALogBridge.emit` as the origin of all log messages.
5. **Recursion & Duplication Prevention:**
   - The bridge ignores any record where `record.name == "nvda"` or `getattr(record, "_nvda_bridged", False)`.
   - The original record is marked `record._nvda_bridged = True`.
   - An auxiliary filter is installed on NVDA's `logHandler` to drop original records already bridged, ensuring zero duplicate warnings or errors.

### 2.2 Complete Implementation Design of `utils/logger.py`

```python
# -*- coding: utf-8 -*-
"""Standard logging facade and NVDA logHandler bridge.

Pure Python packages use standard library logging:
    import logging
    log = logging.getLogger(__name__)

When running inside NVDA, `attach_nvda_log_bridge()` connects standard
library logging to NVDA's authoritative `logHandler.log`, ensuring:
1. Records receive `record.name == "nvda"` so NVDA does not drop DEBUG/INFO logs.
2. Caller `codepath` is preserved in NVDA log entries.
3. Recursion and duplicate messages are strictly prevented.
4. When running outside NVDA (pure pytest, worker), this module is a clean no-op.
"""

from __future__ import annotations

import logging
from typing import Any


def get_logger(name: str) -> logging.Logger:
	"""Return a standard library logger for the given module name."""
	return logging.getLogger(name)


class NVDALogBridge(logging.Handler):
	"""Logging handler that routes standard library LogRecords to NVDA's logHandler."""

	def emit(self, record: logging.LogRecord) -> None:
		# Guard against infinite recursion: ignore records originating from NVDA or already bridged
		if record.name == "nvda" or getattr(record, "_nvda_bridged", False):
			return

		try:
			from logHandler import log as nvda_log

			# Mark original record so downstream handlers/filters know it was bridged
			record._nvda_bridged = True

			# Extract formatted message
			msg = record.getMessage()

			# Preserve true caller code path: e.g. "config.state._notify_provider_state_changed"
			if record.funcName and record.funcName != "<module>":
				codepath = f"{record.name}.{record.funcName}"
			else:
				codepath = record.name

			# Dispatch through NVDA logger so new record has name == 'nvda'
			nvda_log._log(
				record.levelno,
				msg,
				(),
				exc_info=record.exc_info,
				extra={"codepath": codepath},
				codepath=codepath,
				stack_info=record.stack_info,
			)
		except Exception:
			self.handleError(record)


def _drop_bridged_filter(record: logging.LogRecord) -> bool:
	"""Filter for NVDA's root handler to prevent duplicate entries for bridged records."""
	return not getattr(record, "_nvda_bridged", False)


def attach_nvda_log_bridge(logger_name: str | None = None) -> bool:
	"""Attach NVDALogBridge to the specified logger or root logger.

	Returns True if bridge was attached, False if outside NVDA or already attached.
	"""
	try:
		from logHandler import log as nvda_log, logHandler as nvda_handler
	except ImportError:
		return False  # Running in pure Python environment; no-op

	target_logger = logging.getLogger(logger_name)

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

---

## 3. Logging Purge across Pure Packages (18 Files)

Every file listed below currently imports `from logHandler import log`. All 18 are pure domain, service, config, provider, prompt, or utility files.

### 3.1 `addon/globalPlugins/AI-assistant/config/state.py`
- **Location:** Line 7
- **Current Code:**
  ```python
  from logHandler import log
  ```
- **Replacement:**
  ```python
  import logging

  log = logging.getLogger(__name__)
  ```
- **Logged Events:** Lines 46, 76, 94 (`log.exception(...)` during listener notification).
- **Other NVDA Imports:** None.

### 3.2 `addon/globalPlugins/AI-assistant/config/yaml_store.py`
- **Location:** Line 10
- **Current Code:**
  ```python
  import yaml
  from logHandler import log
  ```
- **Replacement:**
  ```python
  import logging
  import yaml

  log = logging.getLogger(__name__)
  ```
- **Logged Events:** Line 42 (`log.exception("Error loading configuration from %s", self._file_path)`).
- **Other NVDA Imports:** None.

### 3.3 `addon/globalPlugins/AI-assistant/utils/crypto.py`
- **Location:** Line 20
- **Current Code:**
  ```python
  from logHandler import log
  ```
- **Replacement:**
  ```python
  import logging

  log = logging.getLogger(__name__)
  ```
- **Logged Events:** Line 92 (`log.warning(...)`), Line 161 (`log.exception(...)`), Line 174 (`log.warning(...)`), Line 181 (`log.exception(...)`), Line 203 (`log.exception(...)`).
- **Other NVDA Imports:** None. Uses Windows `ctypes.windll.crypt32` directly.

### 3.4 `addon/globalPlugins/AI-assistant/service/base.py`
- **Location:** Line 8
- **Current Code:**
  ```python
  from logHandler import log
  ```
- **Replacement:**
  ```python
  import logging

  log = logging.getLogger(__name__)
  ```
- **Logged Events:** Line 92 (`log.exception(...)`), Line 96 (`log.exception(...)`), Line 156 (`log.exception(...)`), Line 161 (`log.debug(...)`).
- **Other NVDA Imports:** None.

### 3.5 `addon/globalPlugins/AI-assistant/service/model_cache.py`
- **Location:** Line 29
- **Current Code:**
  ```python
  from logHandler import log
  ```
- **Replacement:**
  ```python
  import logging

  log = logging.getLogger(__name__)
  ```
- **Logged Events:** Lines 226, 234, 295, 301 (`log.debug(...)`), Lines 281, 353, 361, 368, 379 (`log.exception(...)`).
- **Other NVDA Imports:** None.

### 3.6 `addon/globalPlugins/AI-assistant/service/error_reporter.py`
- **Location:** Line 10
- **Current Code:**
  ```python
  from logHandler import log
  ```
- **Replacement:**
  ```python
  import logging

  log = logging.getLogger(__name__)
  ```
- **Logged Events:** Lines 49, 86 (`log.exception(...)`), Line 64 (`log.error(...)`).
- **Other NVDA Imports:** None (`builtins._` fallback present).

### 3.7 `addon/globalPlugins/AI-assistant/service/chat/coordinator.py`
- **Location:** Line 9
- **Current Code:**
  ```python
  from logHandler import log
  ```
- **Replacement:**
  ```python
  import logging

  log = logging.getLogger(__name__)
  ```
- **Logged Events:** Lines 151, 164, 254, 267, 336 (`log.debug(...)`), Line 318 (`log.warning(...)`).
- **Other NVDA Imports:** None.

### 3.8 `addon/globalPlugins/AI-assistant/service/chat/repository_backends.py`
- **Location:** Line 13
- **Current Code:**
  ```python
  from logHandler import log
  ```
- **Replacement:**
  ```python
  import logging

  log = logging.getLogger(__name__)
  ```
- **Logged Events:** Lines 151, 232, 251 (`log.exception(...)`).
- **Other NVDA Imports:** None.

### 3.9 `addon/globalPlugins/AI-assistant/providers/litert_manager.py`
- **Location:** Line 13
- **Current Code:**
  ```python
  from logHandler import log
  ```
- **Replacement:**
  ```python
  import logging

  log = logging.getLogger(__name__)
  ```
- **Logged Events:** Lines 201, 303, 307 (`log.info(...)`), Lines 203, 296, 344, 350 (`log.warning(...)`).
- **Other NVDA Imports:** None.

### 3.10 `addon/globalPlugins/AI-assistant/providers/llama_manager.py`
- **Location:** Line 10
- **Current Code:**
  ```python
  from logHandler import log
  ```
- **Replacement:**
  ```python
  import logging

  log = logging.getLogger(__name__)
  ```
- **Logged Events:** Line 234 (`log.info(...)`).
- **Other NVDA Imports:** None.

### 3.11 `addon/globalPlugins/AI-assistant/providers/provider_proxy.py`
- **Location:** Line 7
- **Current Code:**
  ```python
  from logHandler import log
  ```
- **Replacement:**
  ```python
  import logging

  log = logging.getLogger(__name__)
  ```
- **Logged Events:** Line 26 (`log.warning(...)`), Line 93 (`log.exception(...)`).
- **Other NVDA Imports:** None.

### 3.12 `addon/globalPlugins/AI-assistant/providers/_provider_runtime.py`
- **Location:** Line 7
- **Current Code:**
  ```python
  from logHandler import log
  ```
- **Replacement:**
  ```python
  import logging

  log = logging.getLogger(__name__)
  ```
- **Logged Events:** Line 113 (`log.exception(...)`).
- **Other NVDA Imports:** None.

### 3.13 `addon/globalPlugins/AI-assistant/providers/adapters/openai_compat.py`
- **Location:** Line 23
- **Current Code:**
  ```python
  from logHandler import log
  ```
- **Replacement:**
  ```python
  import logging

  log = logging.getLogger(__name__)
  ```
- **Logged Events:** Lines 230, 443, 534 (`log.debug(...)`).
- **Other NVDA Imports:** None.

### 3.14 `addon/globalPlugins/AI-assistant/providers/runtime/download.py`
- **Location:** Line 27
- **Current Code:**
  ```python
  from logHandler import log
  ```
- **Replacement:**
  ```python
  import logging

  log = logging.getLogger(__name__)
  ```
- **Logged Events:** Lines 112, 251, 342 (`log.info(...)`), Line 316 (`log.warning(...)`), Lines 387, 399, 421 (`log.debug(...)`).
- **Other NVDA Imports:** None.

### 3.15 `addon/globalPlugins/AI-assistant/providers/runtime/manager.py`
- **Location:** Line 12
- **Current Code:**
  ```python
  from logHandler import log
  ```
- **Replacement:**
  ```python
  import logging

  log = logging.getLogger(__name__)
  ```
- **Logged Events:** Line 54 (`log.info(...)`).
- **Other NVDA Imports:** None.

### 3.16 `addon/globalPlugins/AI-assistant/providers/runtime/model_download.py`
- **Location:** Line 21
- **Current Code:**
  ```python
  from logHandler import log
  ```
- **Replacement:**
  ```python
  import logging

  log = logging.getLogger(__name__)
  ```
- **Logged Events:** Lines 98, 148 (`log.info(...)`).
- **Other NVDA Imports:** None.

### 3.17 `addon/globalPlugins/AI-assistant/prompts/base.py`
- **Location:** Lines 6–12
- **Current Code:**
  ```python
  try:
  	from logHandler import log
  except Exception:
  	import logging

  	log = logging.getLogger(__name__)
  ```
- **Replacement:**
  ```python
  import logging

  log = logging.getLogger(__name__)
  ```
- **Logged Events:** Lines 71, 80, 88 (`log.debug(...)`).
- **Other NVDA Imports:** None.

### 3.18 `addon/globalPlugins/AI-assistant/observability/reporter.py`
- **Location:** Line 7
- **Current Code:**
  ```python
  from logHandler import log
  ```
- **Replacement:**
  ```python
  import logging

  log = logging.getLogger(__name__)
  ```
- **Logged Events:** Lines 38, 45 (`log.exception(...)`).
- **Other NVDA Imports:** None.

---

## 4. Language Resolver Decoupling in `config/settings.py`

### 4.1 Current Violation
`addon/globalPlugins/AI-assistant/config/settings.py`:
- Line 8: `import languageHandler` (unconditional top-level import).
- Line 200 in `get_effective_language()`:
  ```python
  language_value = get_language()
  if not language_value or language_value == defaults.DEFAULT_LANGUAGE:
      language_value = languageHandler.getLanguage() or "en"
  ```
When running unit tests or standalone execution without `../nvda` in `sys.path`, importing `config/settings.py` immediately crashes with `ModuleNotFoundError: No module named 'languageHandler'`.

### 4.2 Decoupled Port Design
Introduce `register_language_resolver(resolver: Callable[[], str] | None) -> None`:
- Decouples `config.settings` from any direct knowledge of NVDA's `languageHandler`.
- Allows NVDA plugin startup to register `languageHandler.getLanguage`.
- Allows pure unit tests to register custom callbacks (or None) without monkeypatching global NVDA modules.
- Provides lazy fallback if `languageHandler` is available, and defaults safely to `"en"`.

### 4.3 Code Changes in `config/settings.py`

#### Top of File (Replacing line 8):
```python
# Before (lines 6-10):
from typing import Any, TYPE_CHECKING

import languageHandler
from . import defaults

# After:
from collections.abc import Callable
from typing import Any, TYPE_CHECKING

from . import defaults

_language_resolver: Callable[[], str] | None = None


def register_language_resolver(resolver: Callable[[], str] | None) -> None:
	"""Register a callback returning the current UI language.

	In NVDA, this is wired to languageHandler.getLanguage during plugin startup.
	In standalone pure-Python environments, a custom callback or None can be used.
	"""
	global _language_resolver
	_language_resolver = resolver
```

#### In `get_effective_language()` (Replacing lines 193–202):
```python
# Before:
def get_effective_language() -> str:
	"""Return the effective prompt language to use for prompt generation.

	If the stored setting is unset or set to the auto default, use NVDA's current UI language.
	"""
	language_value = get_language()
	if not language_value or language_value == defaults.DEFAULT_LANGUAGE:
		language_value = languageHandler.getLanguage() or "en"
	return language_value

# After:
def get_effective_language() -> str:
	"""Return the effective prompt language to use for prompt generation.

	If the stored setting is unset or set to the auto default, query the registered
	language resolver, falling back to NVDA's languageHandler if available, and finally 'en'.
	"""
	language_value = get_language()
	if not language_value or language_value == defaults.DEFAULT_LANGUAGE:
		if _language_resolver is not None:
			try:
				return _language_resolver() or "en"
			except Exception:
				return "en"
		try:
			import languageHandler
			return languageHandler.getLanguage() or "en"
		except ImportError:
			return "en"
	return language_value
```

### 4.4 Host Layer Wiring
In the NVDA-affine plugin layer (`addon/globalPlugins/AI-assistant/plugin/__init__.py` and `plugin/application.py`):
1. In `plugin/__init__.py`:
   ```python
   # -*- coding: utf-8 -*-
   from __future__ import annotations

   import addonHandler
   import languageHandler

   from ..config.settings import register_language_resolver
   from ..utils.logger import attach_nvda_log_bridge

   addonHandler.initTranslation()
   register_language_resolver(languageHandler.getLanguage)
   attach_nvda_log_bridge()

   from .application import AIAssistantApplication
   from .controller import GlobalPlugin
   from .types import PluginServices

   __all__ = [
   	"AIAssistantApplication",
   	"GlobalPlugin",
   	"PluginServices",
   ]
   ```
2. In `plugin/application.py`:
   In `AIAssistantApplication.__init__`, also ensure:
   ```python
   register_language_resolver(languageHandler.getLanguage)
   attach_nvda_log_bridge()
   ```

### 4.5 Test Ergonomics Impact
In existing pure unit tests:
- `tests/config/test_settings_activation.py` currently monkeypatches `languageHandler.getLanguage`.
- With this decoupling, pure tests can either:
  a) Call `settings_module.register_language_resolver(lambda: "en")`.
  b) Or rely on the built-in fallback to `"en"` without requiring `languageHandler` to exist on `sys.path`.
- This unblocks running `test_settings_activation.py` in standalone pure-Python environments.

---

## 5. Verification Matrix & Safety Analysis

| Component | Target File | Verification Check |
|---|---|---|
| Logging Facade | `utils/logger.py` | Importable in pure Python without NVDA on sys.path |
| Bridge Handler | `utils/logger.py` | `NVDALogBridge` attaches to logger without raising errors |
| Filtering & Recurse Guard | `utils/logger.py` | Records with `record.name == "nvda"` are not re-emitted; no infinite loops |
| Language Port | `config/settings.py` | Importable without `languageHandler` on sys.path; returns `"en"` by default |
| Custom Resolver | `config/settings.py` | `register_language_resolver(lambda: "de")` correctly yields `"de"` |
| 18 Pure Modules | Listed in §3 | Zero `from logHandler import log` statements remain |
| AST Boundary Test | `tests/test_import_boundaries.py` | Passes 100% with 0 violations across all pure packages |
| Ruff Linter | `pyproject.toml` | `uv run ruff check .` passes with 0 violations under `TID251` |
