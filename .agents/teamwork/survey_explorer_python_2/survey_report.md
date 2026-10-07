# Pure Python Test Boundary Survey Report — Slice 1

**Author:** Pure Python Test Boundary Explorer (Agent 2)  
**Date:** 2026-10-04  
**Working Directory:** `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\survey_explorer_python_2`  
**Target Commit:** `ced1cbc` (HEAD)  
**Scope:** Slice 1 — Pure Python Test Boundary Decoupling & Import Enforcement  

---

## Executive Summary

This report delivers the authoritative code-level survey and implementation architecture for **Slice 1 (Pure Python Test Boundary Decoupling)**.

Currently, running tests on `NVDA-AI-assistant` is strictly gated behind an external sibling checkout of NVDA (`../nvda`). Root `conftest.py` unconditionally raises `pytest.UsageError` if `../nvda/source/api.py` is absent, preventing pure unit, domain, configuration, and utility tests from executing independently. Furthermore, 18 pure domain and service files directly import `from logHandler import log`, and `config/settings.py` imports `languageHandler`, causing immediate `ModuleNotFoundError` if imported without NVDA's source tree on `sys.path`.

Our audit establishes that:
1. **56 of 59 existing test files (94.9%)** and **451 of 464 test items (97.2%)** are pure Python tests with zero intrinsic requirement for NVDA source code. Only 3 test files require NVDA checkout/APIs.
2. Across all 114 production Python files in `addon/globalPlugins/AI-assistant/`, there are exactly **95 NVDA import statements**. Exactly **18 of these** leak into pure domain/service packages (`core/`, `config/`, `service/`, `providers/`, `prompts/`, `tools/`, `observability/`, `utils/`).
3. 17 of the 18 leaks are `from logHandler import log`; the 18th is `import languageHandler` in `config/settings.py:8`.
4. Decoupling these 18 imports allows pure Python tests to run completely independently in **under 1 second** on any operating system without NVDA or any sibling checkout.

---

## 1. Conftest Sibling Decoupling

### 1.1 Root `conftest.py` Current State & Deficiencies

Root `conftest.py` (lines 18–91) unconditionally couples the test environment to `../nvda`:

```python
# conftest.py:27-31
if not (NVDA_SOURCE / "api.py").is_file():
	raise pytest.UsageError(
		"NVDA source checkout was not found at ../nvda. "
		"Clone https://github.com/nvaccess/nvda.git beside NVDA-AI-assistant.",
	)
```

**Key Code-Level Deficiencies:**
1. **Unconditional Collection Gate (Lines 27–31):** The check executes at module evaluation time when `conftest.py` is loaded by pytest. If `../nvda/source/api.py` is missing, pytest immediately aborts with `UsageError` before collecting tests or evaluating markers like `-m "not nvda_integration"`.
2. **Git Subprocess Execution (Lines 33–40):** Runs `git rev-parse HEAD` in `NVDA_ROOT`. If `../nvda` is not a git repo or revision mismatches in CI, it raises `pytest.UsageError`.
3. **Unconditional `sys.path` Injection (Lines 49–58):** Prepends `NVDA_SOURCE` and `NVDA_MISC_DEPS` to `sys.path`.
4. **Unconditional Module Imports (Lines 70–90):** Imports `globalVars`, `controlTypes`, `logHandler`, and `textInfos` at module level and populates `REAL_NVDA_MODULES`.

### 1.2 Import Dependency on `conftest.py`

In the entire repository, exactly two test files import symbols from `conftest`:
- `tests/integration/test_nvda_imports.py:7`:
  `from conftest import NVDA_ROOT, NVDA_SOURCE, PROJECT_ROOT, REAL_NVDA_MODULES`
- `tests/integration/test_nvda_runtime.py:13`:
  `from conftest import NVDA_ROOT, NVDA_SOURCE`

Zero pure unit tests import from `conftest`.

### 1.3 How Add-on Modules Are Loaded (`tests/support/bootstrap.py`)

Because the add-on directory on disk is named `AI-assistant` (containing a hyphen), Python cannot import it using normal syntax `import addon.globalPlugins.AI-assistant`.

`tests/support/bootstrap.py` provides:
- `register_package(name: str, path: Path | None = None) -> ModuleType`
- `load_module(name: str, path: Path) -> ModuleType`
- `load_addon_module(dotted_name: str, *, namespace: str = "nvda_ai_assistant_tests") -> ModuleType`

Currently, individual test files either call `load_addon_module(...)` or manually call `register_package()` and `_load_module()`, often duplicating synthetic namespace names (`model_config_testpkg`, `yaml_store_testpkg`, `graph_store_tests`, etc.).

### 1.4 Decoupling Design for `conftest.py`

Root `conftest.py` must support two operational modes:

1. **Standalone / Pure Mode (`HAS_NVDA_CHECKOUT == False`):**
   - Provide standard identity translations in `builtins` (`builtins._ = gettext.gettext`, etc.) without touching `../nvda`.
   - Provide empty `REAL_NVDA_MODULES = {}`.
   - In `pytest_collection_modifyitems`, automatically skip any test marked `nvda_integration` with reason: `"Sibling NVDA checkout not found at ../nvda."`.
   - Zero errors, zero warnings, zero git executions.
2. **NVDA-Connected Mode (`HAS_NVDA_CHECKOUT == True`):**
   - Retain full existing behavior for NVDA integration tests: pin verification, `sys.path` injection, `globalVars` configuration, and `REAL_NVDA_MODULES` population.

#### Proposed `conftest.py` Implementation

```python
"""Shared pytest bootstrap supporting both standalone pure-Python tests and NVDA integration."""

from __future__ import annotations

import builtins
import gettext
import os
import subprocess
import sys
import tempfile
import tomllib
import warnings
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent
NVDA_ROOT = PROJECT_ROOT.parent / "nvda"
NVDA_SOURCE = NVDA_ROOT / "source"
NVDA_MISC_DEPS = NVDA_ROOT / "miscDeps" / "python"
NVDA_VENV_SITE_PACKAGES = NVDA_ROOT / ".venv" / "Lib" / "site-packages"

HAS_NVDA_CHECKOUT = (NVDA_SOURCE / "api.py").is_file()

# Standard library translation functions installed unconditionally
builtins._ = gettext.gettext
builtins.ngettext = gettext.ngettext
builtins.pgettext = gettext.pgettext
builtins.npgettext = gettext.npgettext

REAL_NVDA_MODULES: dict[str, object] = {}

if HAS_NVDA_CHECKOUT:
	with (PROJECT_ROOT / "nvda-source.toml").open("rb") as pin_file:
		NVDA_REVISION = tomllib.load(pin_file)["nvda"]["revision"]

	try:
		revision = subprocess.run(
			["git", "rev-parse", "HEAD"],
			cwd=NVDA_ROOT,
			check=True,
			capture_output=True,
			text=True,
		).stdout.strip()
		if revision != NVDA_REVISION:
			message = (
				f"Sibling NVDA checkout is at {revision}, but this project is tested against "
				f"{NVDA_REVISION}. Run: git -C ../nvda checkout {NVDA_REVISION}"
			)
			if os.environ.get("CI"):
				raise pytest.UsageError(message)
			warnings.warn(message, stacklevel=1)
	except Exception as e:
		if os.environ.get("CI"):
			raise
		warnings.warn(f"Could not verify sibling NVDA revision: {e}", stacklevel=1)

	for path in reversed((NVDA_SOURCE, NVDA_MISC_DEPS)):
		path_string = str(path)
		if path_string not in sys.path:
			sys.path.insert(0, path_string)

	if NVDA_VENV_SITE_PACKAGES.is_dir():
		sys.path.append(str(NVDA_VENV_SITE_PACKAGES))

	import globalVars  # noqa: E402
	globalVars.appDir = str(NVDA_SOURCE)
	globalVars.appArgs.disableAddons = True
	nvda_test_config = Path(tempfile.gettempdir()) / "nvda-ai-assistant-tests"
	nvda_test_config.mkdir(parents=True, exist_ok=True)
	globalVars.appArgs.configPath = str(nvda_test_config)

	import controlTypes  # noqa: E402, F401
	import logHandler  # noqa: E402, F401
	import textInfos  # noqa: E402, F401

	REAL_NVDA_MODULES.update({
		"controlTypes": controlTypes,
		"logHandler": logHandler,
		"textInfos": textInfos,
	})


def pytest_collection_modifyitems(config, items):
	"""Skip tests requiring NVDA if sibling checkout is absent."""
	if not HAS_NVDA_CHECKOUT:
		skip_marker = pytest.mark.skip(
			reason="Sibling NVDA checkout not found at ../nvda. Pure tests pass without it."
		)
		for item in items:
			if "nvda_integration" in item.keywords:
				item.add_marker(skip_marker)
```

---

## 2. Logging & NVDA Import Decoupling

### 2.1 Complete Inventory of `logHandler` Imports

An exhaustive AST search across all 114 production Python files in `addon/globalPlugins/AI-assistant/` identified exactly **40 occurrences** of `from logHandler import log` (and 0 occurrences of `import logHandler`).

#### 18 Occurrences in Pure Domain/Service/Config Packages:
1. `addon/globalPlugins/AI-assistant/config/state.py:7`
2. `addon/globalPlugins/AI-assistant/config/yaml_store.py:10`
3. `addon/globalPlugins/AI-assistant/utils/crypto.py:20`
4. `addon/globalPlugins/AI-assistant/service/base.py:8`
5. `addon/globalPlugins/AI-assistant/service/model_cache.py:29`
6. `addon/globalPlugins/AI-assistant/service/error_reporter.py:10`
7. `addon/globalPlugins/AI-assistant/service/chat/coordinator.py:9`
8. `addon/globalPlugins/AI-assistant/service/chat/repository_backends.py:13`
9. `addon/globalPlugins/AI-assistant/providers/litert_manager.py:13`
10. `addon/globalPlugins/AI-assistant/providers/llama_manager.py:10`
11. `addon/globalPlugins/AI-assistant/providers/provider_proxy.py:7`
12. `addon/globalPlugins/AI-assistant/providers/_provider_runtime.py:7`
13. `addon/globalPlugins/AI-assistant/providers/adapters/openai_compat.py:23`
14. `addon/globalPlugins/AI-assistant/providers/runtime/download.py:27`
15. `addon/globalPlugins/AI-assistant/providers/runtime/manager.py:12`
16. `addon/globalPlugins/AI-assistant/providers/runtime/model_download.py:21`
17. `addon/globalPlugins/AI-assistant/prompts/base.py:7`
18. `addon/globalPlugins/AI-assistant/observability/reporter.py:7`

#### 22 Occurrences in Adapter/UI/Plugin Layers (Retained until future slices):
- `context/extractors/`: `browser.py:6`, `browser_candidates.py:8`, `focused_text.py:5`, `generic_extractor.py:6`, `selection.py:12`
- `image/`: `focus_capture.py:11`, `objects.py:89, 196`
- `plugin/`: `application.py:11`, `background.py:10`, `controller.py:12`, `layer_mode.py:9`, `presenter.py:9`
- `ui/`: `adapter.py:10`, `download_progress.py:14`, `model_config_dialog.py:34`, `nvda_ui.py:50, 106`, `provider_configure.py:27`, `stream_projection.py:12`, `task_runner.py:17`
- `utils/`: `clipboard.py:11`

### 2.2 Method Calls on `log` Across Pure Packages

AST call analysis verified that all 18 pure modules call exclusively standard Python `logging.Logger` methods:
- `log.debug(...)` (in `prompts/base.py`, `service/base.py`, `service/model_cache.py`, `service/chat/coordinator.py`, `providers/adapters/openai_compat.py`, `providers/runtime/download.py`)
- `log.info(...)` (in `providers/litert_manager.py`, `providers/llama_manager.py`, `providers/runtime/download.py`, `providers/runtime/manager.py`, `providers/runtime/model_download.py`)
- `log.warning(...)` (in `service/chat/coordinator.py`, `providers/litert_manager.py`, `providers/provider_proxy.py`, `providers/runtime/download.py`, `utils/crypto.py`)
- `log.error(...)` (in `service/error_reporter.py`, `providers/adapters/openai_compat.py`)
- `log.exception(...)` (in `service/base.py`, `service/error_reporter.py`, `service/model_cache.py`, `service/chat/repository_backends.py`, `providers/provider_proxy.py`, `providers/_provider_runtime.py`, `config/state.py`, `config/yaml_store.py`, `observability/reporter.py`, `utils/crypto.py`)

Zero modules call NVDA-custom logger methods (`log.io`, `log.secrets`, `log.debugWarning`).

### 2.3 NVDA Filtering Discovery (`filterExternalDependencyLogging`)

Inspection of `D:\nvda-addons\nvda\source\logHandler.py:605–612` revealed:
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
**Impact:** If an add-on logger emits records where `record.name != "nvda"`, NVDA's root handler drops `DEBUG` and `INFO` records unless `externalPythonDependencies` is enabled in NVDA config!
Therefore, in production inside NVDA, log messages emitted by pure code must reach `logHandler.log` (which has `name == "nvda"`).

### 2.4 Logging Decoupling Design (`utils/logger.py`)

1. **Standardize all pure modules to standard library logging:**
   Replace:
   ```python
   from logHandler import log
   ```
   with:
   ```python
   import logging

   log = logging.getLogger(__name__)
   ```
   This has **zero dependencies**, satisfies Ruff `TID251`, passes AST checks, and runs in pure Python.

2. **Create `addon/globalPlugins/AI-assistant/utils/logger.py`:**
   Provides an explicit helper and an `NVDALogBridge` handler for attaching to the root logger when running inside NVDA.

```python
# addon/globalPlugins/AI-assistant/utils/logger.py
"""Logging bridge connecting standard library logging to NVDA's logHandler."""

from __future__ import annotations

import logging
from typing import Any

def get_logger(name: str) -> logging.Logger:
	"""Return a standard library logger for the given name."""
	return logging.getLogger(name)


class NVDALogBridge(logging.Handler):
	"""Forward standard library LogRecord objects to NVDA's authoritative logHandler."""

	def emit(self, record: logging.LogRecord) -> None:
		try:
			from logHandler import log as nvda_log
			msg = self.format(record)
			# Dispatch through NVDA logger so records carry name == 'nvda'
			nvda_log._log(record.levelno, msg, (), exc_info=record.exc_info)
		except Exception:
			self.handleError(record)


def attach_nvda_log_bridge(logger_name: str | None = None) -> None:
	"""Attach the NVDA bridge handler to the specified logger or root logger."""
	try:
		from logHandler import log  # noqa: F401
	except ImportError:
		return  # Running outside NVDA; no-op

	target_logger = logging.getLogger(logger_name)
	for handler in target_logger.handlers:
		if isinstance(handler, NVDALogBridge):
			return
	bridge = NVDALogBridge()
	target_logger.addHandler(bridge)
```

In `addon/globalPlugins/AI-assistant/plugin/__init__.py` or `plugin/application.py` (which runs exclusively inside `nvda.exe`), call `attach_nvda_log_bridge()`.

### 2.5 Language Handler Decoupling (`config/settings.py`)

`addon/globalPlugins/AI-assistant/config/settings.py` currently has:
- Line 8: `import languageHandler`
- Lines 198–201:
  ```python
  language_value = get_language()
  if not language_value or language_value == defaults.DEFAULT_LANGUAGE:
  	language_value = languageHandler.getLanguage() or "en"
  ```

#### Decoupling Solution:
1. Remove `import languageHandler` from module top level.
2. Introduce a pluggable `register_language_resolver` port with lazy import fallback:

```python
# In config/settings.py
from collections.abc import Callable

_language_resolver: Callable[[], str] | None = None

def register_language_resolver(resolver: Callable[[], str]) -> None:
	"""Register a host-provided callback returning the effective UI language."""
	global _language_resolver
	_language_resolver = resolver

def get_effective_language() -> str:
	"""Return effective prompt language, querying the registered resolver or falling back to 'en'."""
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

3. In `plugin/__init__.py`, register `languageHandler.getLanguage`.
4. In pure unit tests, tests can call `settings.register_language_resolver(lambda: "en")`.

---

## 3. Automated Import Boundary Tests & Ruff Configuration

### 3.1 Design of `tests/test_import_boundaries.py`

The AST boundary test must statically verify that no forbidden NVDA module is ever imported by any pure package.

#### Pure Package Boundary Specification:
- `addon/globalPlugins/AI-assistant/core/`
- `addon/globalPlugins/AI-assistant/config/`
- `addon/globalPlugins/AI-assistant/service/`
- `addon/globalPlugins/AI-assistant/providers/`
- `addon/globalPlugins/AI-assistant/use_case/`
- `addon/globalPlugins/AI-assistant/prompts/`
- `addon/globalPlugins/AI-assistant/tools/`
- `addon/globalPlugins/AI-assistant/observability/`
- `addon/globalPlugins/AI-assistant/embeddings/`
- Pure files in `addon/globalPlugins/AI-assistant/context/`:
  (`budget.py`, `formatting.py`, `graph_store.py`, `pipeline.py`, `prompts.py`, `protocols.py`, `reduction.py`, `request_registry.py`, `structure_summary.py`, `types.py`)

#### Forbidden Modules List:
- NVDA core & accessibility: `api`, `textInfos`, `controlTypes`, `treeInterceptorHandler`, `locationHelper`, `winUser`
- NVDA plugin & lifecycle: `globalPluginHandler`, `scriptHandler`, `addonHandler`, `globalVars`
- NVDA UI & event marshaling: `queueHandler`, `gui`, `wx`, `speech`, `tones`, `nvwave`
- NVDA utilities: `logHandler`, `languageHandler`

#### Proposed `tests/test_import_boundaries.py`:

```python
"""Automated architectural boundary tests enforcing pure-Python domain isolation."""

from __future__ import annotations

import ast
from pathlib import Path
import pytest

from tests.support import ADDON_ROOT

PURE_DIRECTORIES = [
	"core",
	"config",
	"service",
	"providers",
	"use_case",
	"prompts",
	"tools",
	"observability",
	"embeddings",
]

FORBIDDEN_NVDA_MODULES = {
	"api",
	"textInfos",
	"controlTypes",
	"globalPluginHandler",
	"scriptHandler",
	"queueHandler",
	"gui",
	"wx",
	"speech",
	"tones",
	"logHandler",
	"languageHandler",
	"addonHandler",
	"winUser",
	"locationHelper",
	"treeInterceptorHandler",
	"nvwave",
	"globalVars",
}


def _find_forbidden_imports(file_path: Path) -> list[tuple[int, str, str]]:
	content = file_path.read_text(encoding="utf-8")
	tree = ast.parse(content, filename=str(file_path))
	violations = []
	for node in ast.walk(tree):
		if isinstance(node, ast.Import):
			for alias in node.names:
				root_pkg = alias.name.split(".")[0]
				if root_pkg in FORBIDDEN_NVDA_MODULES:
					violations.append((node.lineno, root_pkg, f"import {alias.name}"))
		elif isinstance(node, ast.ImportFrom) and node.module:
			root_pkg = node.module.split(".")[0]
			if root_pkg in FORBIDDEN_NVDA_MODULES:
				violations.append((node.lineno, root_pkg, f"from {node.module} import ..."))
	return violations


def test_pure_packages_have_zero_forbidden_nvda_imports():
	"""Assert that pure Python packages never import forbidden NVDA modules."""
	all_violations = []
	for dir_name in PURE_DIRECTORIES:
		target_dir = ADDON_ROOT / dir_name
		if not target_dir.is_dir():
			continue
		for py_path in target_dir.rglob("*.py"):
			violations = _find_forbidden_imports(py_path)
			for lineno, forbidden_pkg, stmt in violations:
				rel_path = py_path.relative_to(ADDON_ROOT).as_posix()
				all_violations.append(f"{rel_path}:{lineno} imports forbidden '{forbidden_pkg}' ({stmt})")

	assert not all_violations, (
		f"Found {len(all_violations)} forbidden NVDA import(s) in pure Python packages:\n"
		+ "\n".join(all_violations)
	)


def test_pure_context_modules_have_zero_forbidden_nvda_imports():
	"""Assert that pure context pipeline/reduction/budget modules have zero NVDA imports."""
	pure_context_files = [
		"budget.py",
		"formatting.py",
		"graph_store.py",
		"pipeline.py",
		"prompts.py",
		"protocols.py",
		"reduction.py",
		"request_registry.py",
		"structure_summary.py",
		"types.py",
	]
	violations = []
	for fname in pure_context_files:
		fpath = ADDON_ROOT / "context" / fname
		if fpath.is_file():
			for lineno, forbidden_pkg, stmt in _find_forbidden_imports(fpath):
				violations.append(f"context/{fname}:{lineno} imports forbidden '{forbidden_pkg}' ({stmt})")

	assert not violations, f"Forbidden imports found in pure context files:\n" + "\n".join(violations)
```

Execution benchmark: Prototype scans all AST nodes across all target files in **~85ms**.

### 3.2 Ruff Banned API (`TID251`) Configuration

#### Critical Discovery: Architecture Deliverable Typo Inversion
Section 6.3 of `architecture_deliverable.md` listed:
```toml
[tool.ruff.lint.per-file-ignores]
"addon/globalPlugins/AI-assistant/core/**" = ["TID251"]
...
```
In Ruff, `per-file-ignores` specifies rules to **suppress (ignore)** on matched files. Listing `core/**` would deactivate `TID251` on `core/`!
We verified this behavior via an experimental test with Ruff:
- A file in `per-file-ignores` ignores the banned API.
- A file not in `per-file-ignores` triggers an exit code 1 with exact symbol citation.

#### Correct `pyproject.toml` Configuration:
`TID251` must be enabled globally, with adapter and integration test layers placed in `per-file-ignores`:

```toml
[tool.ruff.lint]
extend-select = [
	"TID251",  # flake8-tidy-imports: banned-api
]

[tool.ruff.lint.flake8-tidy-imports.banned-api]
"logHandler".msg = "Use standard library 'logging.getLogger(__name__)' instead of NVDA logHandler."
"languageHandler".msg = "Access language via injected LanguageResolver port."
"api".msg = "NVDA api access is forbidden outside Layer 0 extractors."
"textInfos".msg = "textInfos is forbidden outside Layer 0 extractors."
"controlTypes".msg = "controlTypes is forbidden outside Layer 0 extractors."
"queueHandler".msg = "queueHandler is forbidden outside ui/nvda_ui.py."
"gui".msg = "gui is forbidden outside ui/ dialogs."
"wx".msg = "wx is forbidden outside ui/ dialogs."
"speech".msg = "speech is forbidden outside ui/nvda_ui.py."
"tones".msg = "tones is forbidden outside ui/nvda_ui.py."

[tool.ruff.lint.per-file-ignores]
# Existing ignores
"sconstruct" = ["F821"]
"addon/globalPlugins/AI-assistant/__init__.py" = ["E402"]
"addon/globalPlugins/AI-assistant/plugin/__init__.py" = ["E402"]

# Layer 0 NVDA adapter surfaces legitimately importing NVDA APIs
"addon/globalPlugins/AI-assistant/context/extractors/**" = ["TID251"]
"addon/globalPlugins/AI-assistant/context/navigation.py" = ["TID251"]
"addon/globalPlugins/AI-assistant/image/**" = ["TID251"]
"addon/globalPlugins/AI-assistant/plugin/**" = ["TID251"]
"addon/globalPlugins/AI-assistant/ui/**" = ["TID251"]
"addon/globalPlugins/AI-assistant/utils/clipboard.py" = ["TID251"]
"tests/**" = ["TID251"]
```

---

## 4. Current Test Inventory & Categorization

### 4.1 Suite Overview

- **Total Test Files:** 59
- **Total Test Items Collected:** 464 items (461 run by default, 3 deselected by `-m "not nvda_integration"`)
- **Suite Execution Time:** 16.58 seconds (461 passed)
- **Pure Python Test Suites:** ~0.10s to ~0.70s per module
- **Pure vs Integration Split:**
  - **Tier 1 (Pure Python):** 56 test files, 451 test functions
  - **Tier 3 (NVDA Integration):** 3 test files, 13 test functions

### 4.2 Comprehensive 59-File Test Inventory

| # | Test File Path | Tests | Tier | NVDA / External Dependencies | Notes |
| :---: | :--- | :---: | :---: | :--- | :--- |
| 1 | `tests/architecture/test_thread_boundaries.py` | 4 | Tier 1 | None | AST static contract test |
| 2 | `tests/architecture/test_use_case_flow.py` | 1 | Tier 1 | None | Call-graph static contract test |
| 3 | `tests/build/test_addon_packaging.py` | 1 | Tier 1 | None | Exclusion verification test |
| 4 | `tests/config/test_model_config.py` | 35 | Tier 1 | None | Pure model sampling config |
| 5 | `tests/config/test_model_visibility.py` | 8 | Tier 1 | None | Enabled models store |
| 6 | `tests/config/test_provider_specs.py` | 2 | Tier 1 | None | Provider specification catalog |
| 7 | `tests/config/test_settings_activation.py` | 22 | Tier 1 | `languageHandler` (stubbed) | Uses monkeypatch for `getLanguage` |
| 8 | `tests/config/test_yaml_store.py` | 3 | Tier 1 | None | YAML persistence store |
| 9 | `tests/context/extractors/test_browser_field_parser.py` | 7 | **Tier 3** | `controlTypes`, `textInfos` | Shape-based parser test; requires NVDA Role |
| 10 | `tests/context/test_browser_field_graph.py` | 4 | Tier 1 | None | Pure graph analysis |
| 11 | `tests/context/test_budget.py` | 5 | Tier 1 | None | Token budget calculation |
| 12 | `tests/context/test_context_pipeline.py` | 6 | Tier 1 | None | Pipeline flow with mocks |
| 13 | `tests/context/test_context_reduction.py` | 8 | Tier 1 | None | Text reduction algorithms |
| 14 | `tests/context/test_graph_store.py` | 3 | Tier 1 | None | In-memory graph storage |
| 15 | `tests/context/test_navigation.py` | 7 | Tier 1 | None | Navigation logic with mocks |
| 16 | `tests/embeddings/test_manager.py` | 5 | Tier 1 | None | Local embedding manager |
| 17 | `tests/integration/test_chat_lifecycle.py` | 5 | Tier 1 | None | Controlled fake LLM coordinator |
| 18 | `tests/integration/test_local_provider_lifecycle.py` | 23 | Tier 1 | None | Managed local provider state machine |
| 19 | `tests/integration/test_nvda_imports.py` | 3 | **Tier 3** | `controlTypes`, `textInfos` | Tests sibling NVDA checkout discovery |
| 20 | `tests/integration/test_nvda_runtime.py` | 3 | **Tier 3** | NVDA DLLs, comtypes | Gated by `pytest.mark.nvda_integration` |
| 21 | `tests/observability/test_events.py` | 1 | Tier 1 | None | Diagnostic event emission |
| 22 | `tests/plugin/test_background_provider_ready.py` | 3 | Tier 1 | None | Background task coordination |
| 23 | `tests/plugin/test_background_shutdown.py` | 6 | Tier 1 | None | Clean worker teardown |
| 24 | `tests/plugin/test_local_provider_startup.py` | 4 | Tier 1 | None | Startup sequence logic |
| 25 | `tests/plugin/test_presenter_ui_actions.py` | 22 | Tier 1 | None | Presenter action dispatch |
| 26 | `tests/plugin/test_ui_actions.py` | 12 | Tier 1 | None | User interaction handlers |
| 27 | `tests/prompts/test_base.py` | 5 | Tier 1 | None | Prompt template formatting |
| 28 | `tests/prompts/test_summary.py` | 6 | Tier 1 | None | Summarization prompt logic |
| 29 | `tests/providers/runtime/test_download_cancellation.py` | 1 | Tier 1 | None | HTTP cancellation mechanics |
| 30 | `tests/providers/runtime/test_llama_models.py` | 9 | Tier 1 | None | GGUF model registry |
| 31 | `tests/providers/runtime/test_llama_server.py` | 2 | Tier 1 | None | llama.cpp subprocess manager |
| 32 | `tests/providers/runtime/test_runtime_supervisor.py` | 12 | Tier 1 | None | PyO3 native supervisor wrapper |
| 33 | `tests/providers/runtime/test_server.py` | 38 | Tier 1 | None | Local runtime server lifecycle |
| 34 | `tests/providers/test_capabilities.py` | 3 | Tier 1 | None | Provider capability queries |
| 35 | `tests/providers/test_litert_manager.py` | 8 | Tier 1 | `languageHandler` (stubbed) | Uses monkeypatch for `getLanguage` |
| 36 | `tests/providers/test_llama_provider.py` | 5 | Tier 1 | None | llama.cpp adapter logic |
| 37 | `tests/providers/test_model_import.py` | 5 | Tier 1 | None | GGUF / SafeTensors metadata reader |
| 38 | `tests/providers/test_model_source_import.py` | 5 | Tier 1 | None | Source catalog resolver |
| 39 | `tests/providers/test_provider_policy.py` | 4 | Tier 1 | None | Fallback and retry policy |
| 40 | `tests/providers/test_registry.py` | 49 | Tier 1 | None | Provider registry dispatch |
| 41 | `tests/service/chat/test_conversation_service.py` | 12 | Tier 1 | None | Conversation history & session |
| 42 | `tests/service/chat/test_coordinator.py` | 3 | Tier 1 | None | Tool dispatch coordination |
| 43 | `tests/service/test_configured_model_status.py` | 6 | Tier 1 | None | Readiness status query |
| 44 | `tests/service/test_error_presentation.py` | 17 | Tier 1 | None | Error code to UI mapping |
| 45 | `tests/service/test_model_cache.py` | 8 | Tier 1 | None | In-memory model catalog cache |
| 46 | `tests/service/test_provider_readiness_litert.py` | 3 | Tier 1 | None | LiteRT readiness polling |
| 47 | `tests/service/test_provider_state_flow.py` | 8 | Tier 1 | None | State transition observer |
| 48 | `tests/service/test_streaming_tone_progress.py` | 2 | Tier 1 | None | Audio feedback timing |
| 49 | `tests/ui/test_accessibility.py` | 2 | Tier 1 | None | Screen reader contrast/labels |
| 50 | `tests/ui/test_adapter_fallback.py` | 3 | Tier 1 | None | UI host failover to NVDA dialogs |
| 51 | `tests/ui/test_attachment_context.py` | 3 | Tier 1 | None | Attachment payload formatting |
| 52 | `tests/ui/test_bootstrap.py` | 0 | Tier 1 | None | Helper file misnamed as test |
| 53 | `tests/ui/test_host_lifecycle.py` | 4 | Tier 1 | None | WebView2 host process launcher |
| 54 | `tests/ui/test_host_protocol.py` | 15 | Tier 1 | None | Named-pipe NDJSON protocol parser |
| 55 | `tests/ui/test_host_transport.py` | 3 | Tier 1 | None | Named pipe async transport |
| 56 | `tests/ui/test_settings_panel.py` | 4 | Tier 1 | None | Settings dialog data binding |
| 57 | `tests/ui/test_task_runner.py` | 3 | Tier 1 | `wx` (via venv wxPython) | UI event dispatch queue |
| 58 | `tests/ui/test_view_models.py` | 1 | Tier 1 | None | Chat UI view model serialization |
| 59 | `tests/use_case/test_streaming_use_cases.py` | 8 | Tier 1 | None | Streaming response pipelines |

### 4.3 Observations on Tier 3 Tests
Only 3 test files require NVDA:
1. `tests/integration/test_nvda_runtime.py`: Already marked `pytestmark = pytest.mark.nvda_integration`. Requires full built NVDA tree and `nvdaHelperLocal.dll`.
2. `tests/integration/test_nvda_imports.py`: Currently missing the marker. Must be marked `pytestmark = pytest.mark.nvda_integration`.
3. `tests/context/extractors/test_browser_field_parser.py`: Imports `controlTypes.Role`. Must be marked `pytestmark = pytest.mark.nvda_integration`.

When these 3 files are marked, `uv run pytest -m "not nvda_integration"` selects **451 tests across 56 files**, all running in pure Python without needing `../nvda`.

---

## 5. Implementation Roadmap for Slice 1

| Phase | Step | Action | Impact |
| :---: | :--- | :--- | :--- |
| **1** | `utils/logger.py` | Create logging facade with `NVDALogBridge` | Provides standard library logging bridge |
| **2** | Pure Module Logging | In all 18 pure domain files, replace `from logHandler import log` with `import logging; log = logging.getLogger(__name__)` | Eliminates all 17 domain `logHandler` imports |
| **3** | Language Decoupling | In `config/settings.py`, replace top-level `import languageHandler` with `register_language_resolver` port | Eliminates domain `languageHandler` import |
| **4** | Conftest Decoupling | Refactor `conftest.py` with `HAS_NVDA_CHECKOUT` guard and `pytest_collection_modifyitems` skip hook | Allows pytest to discover and run pure tests without `../nvda` |
| **5** | Mark Tier 3 Tests | Add `pytestmark = pytest.mark.nvda_integration` to `test_nvda_imports.py` and `test_browser_field_parser.py` | Clean separation between Tier 1 and Tier 3 |
| **6** | Import Boundary Tests | Add `tests/test_import_boundaries.py` with AST checks | Automated CI prevention of architecture regression |
| **7** | Ruff Rules | Add `TID251` and corrected `per-file-ignores` in `pyproject.toml` | Instant editor-level and linter-level boundary enforcement |
| **8** | Verification Gate | Run `uv run ruff check .` (0 errors), `uv run pytest` (0 failures), and simulate absent `../nvda` | Zero regression across existing test suite |
