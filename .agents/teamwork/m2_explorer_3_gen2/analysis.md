# Architecture Analysis & Concrete Fix Strategy: AST Boundary Tests & Ruff Banned API Rules

**Agent**: Milestone 2 Explorer 3 (Iteration 2)  
**Working Directory**: `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m2_explorer_3_gen2`  
**Target Milestone**: Milestone 2 (Slice 1 Pure Python Test Boundary Decoupling & Import Enforcement)  
**Date**: 2026-10-04  

---

## Executive Summary

Following the **INTEGRITY VIOLATION** verdict from the Forensic Auditor (`m2_auditor_1_gen2`) and the adversarial bypass vectors exposed by Challenger 2 (`m2_challenger_2_gen2`), this report establishes an exhaustive, watertight fix strategy for architectural boundary enforcement.

The investigation conclusively proved:
1. **Pure Utils Files Omission**: `tests/test_import_boundaries.py` scanned only `PURE_DIRECTORIES` and 10 `PURE_CONTEXT_FILES`. The 3 pure utility files (`utils/crypto.py`, `utils/markdown.py`, `utils/mathml.py`) have zero NVDA dependencies but were completely unmonitored by the AST test.
2. **AST Scanner Evasion Holes**: The AST scanner in `tests/test_import_boundaries.py` contained a raw byte pre-filter and explicitly required `node.level == 0 and node.module`. This caused 10 out of 19 syntactic import forms to evade detection, including 100% of relative import variants (`from .api import ...`, `from .. import api`), dynamic import kwargs (`__import__(name="api")`), and escaped tokens (`\x61pi`). Eliminating the pre-filter is safe because parsing all 110 pure files takes only 60.75ms (well within the 150ms SLA budget).
3. **Layer 0 Leaks in Pure Packages**:
   - `service/error_reporter.py:46` (`from ..ui import nvda_ui`): **FORBIDDEN**. Layering violation. Decouple via an injected notifier callback port (`register_error_notifier`).
   - `use_case/focus_image.py:12` (`from ..image import capture_focused_object`): **FORBIDDEN**. Crashes with `ModuleNotFoundError: No module named 'logHandler'` when NVDA is absent. Must route image capture through `ContextPipeline` using `ExtractionIntent(requests=(FocusedElementImageRequest(),))` (matching `use_case/image.py`), or inject a capture port.
   - `service/error_presentation.py:71` (`from ..image.screen_curtain import ScreenCurtainError`): **FORBIDDEN**. Move `ScreenCurtainError` definition to pure errors layer (`core/errors.py`) to eliminate impure import.
   - `use_case/structure_summary.py:11` (`from ..context.navigation import build_llm_navigation_candidates`): **HYBRID SMELL**. The imported symbols are pure data algorithms, but `context/navigation.py` also contains `resolve_and_move_target` which imports `winUser` and `textInfos`. Split the NVDA action logic into `plugin/browser_navigation.py` so `context/navigation.py` becomes 100% pure and can join `PURE_CONTEXT_FILES`.
4. **`pyproject.toml` Parity Gap**: 6 forbidden NVDA host modules present in the AST test (`addonHandler`, `globalVars`, `winUser`, `locationHelper`, `treeInterceptorHandler`, `nvwave`) were missing from Ruff's `TID251` configuration. Adding them yields 0 lint errors across the current codebase because all legitimate call sites reside in Layer 0 files that already possess `per-file-ignores`.

---

## 1. Focus Area 1: Pure Utils Files Boundary Scanning

### 1.1 Current Architecture & Evidence
Inspection of `addon/globalPlugins/AI-assistant/utils/` reveals 6 files:
| File | Classification | Dependencies | Current Test Coverage |
|---|---|---|---|
| `utils/crypto.py` | **Pure Module** | Windows DPAPI via standard `ctypes`, `logging.getLogger(__name__)`. 0 NVDA imports. | **UNMONITORED** |
| `utils/markdown.py` | **Pure Module** | Standard library `html.escape`, `markdown`, `.mathml`. 0 NVDA imports. | **UNMONITORED** |
| `utils/mathml.py` | **Pure Module** | Pure regex and string parsing, optional `latex2mathml`. 0 NVDA imports. | **UNMONITORED** |
| `utils/clipboard.py` | **Layer 0 Adapter** | `api.getClipData()`, `from logHandler import log`. | Excluded via TID251 |
| `utils/logger.py` | **Layer 0 Adapter** | `NVDALogBridge(logging.Handler)` bridging to `logHandler.log`. | Excluded via TID251 |
| `utils/__init__.py` | **Package Init** | Eagerly imported `from .clipboard import safe_read_clipboard`. | Transitive contamination bug |

In `pyproject.toml` lines 121–122:
```toml
"addon/globalPlugins/AI-assistant/utils/clipboard.py" = ["TID251"]
"addon/globalPlugins/AI-assistant/utils/logger.py" = ["TID251"]
```
Because only `clipboard.py` and `logger.py` are ignored, Ruff `TID251` already actively enforces banned APIs on `crypto.py`, `markdown.py`, and `mathml.py`.
However, `tests/test_import_boundaries.py` only scanned `PURE_DIRECTORIES` and `PURE_CONTEXT_FILES`, leaving pure utils completely unchecked in the automated architecture test.

### 1.2 Concrete Fix Strategy for `tests/test_import_boundaries.py`
Add `PURE_UTILS_FILES` and a dedicated test assertion:

```python
PURE_UTILS_FILES: tuple[str, ...] = (
	"crypto.py",
	"markdown.py",
	"mathml.py",
)


def test_pure_utils_modules_have_zero_forbidden_nvda_imports() -> None:
	"""Assert that pure utility modules (crypto, markdown, mathml) have zero NVDA imports."""
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

Also include `PURE_UTILS_FILES` in the SLA performance test `test_import_boundary_scan_performance_under_150ms()`:
```python
	for fname in PURE_UTILS_FILES:
		fpath = ADDON_ROOT / "utils" / fname
		if fpath.is_file():
			file_count += 1
			_find_forbidden_imports(fpath)
```

### 1.3 Prerequisite: Decoupling `utils/__init__.py`
To eliminate the transitive contamination observed by the Forensic Auditor (where importing `utils.crypto` triggers `utils/__init__.py` which triggers `clipboard.py` which fails on `logHandler`), `utils/__init__.py` must be made pure:

```python
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import TYPE_CHECKING, Any

from .markdown import render_markdown_to_html

__all__ = ["render_markdown_to_html", "safe_read_clipboard"]

if TYPE_CHECKING:
	from .clipboard import safe_read_clipboard


def __getattr__(name: str) -> Any:
	"""Lazy export for Layer 0 clipboard utilities without eager logHandler loading."""
	if name == "safe_read_clipboard":
		from .clipboard import safe_read_clipboard
		return safe_read_clipboard
	raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

---

## 2. Focus Area 2: Fixing AST Import Scanner for Relative & Evasive Imports

### 2.1 Evasion Vector Analysis
Challenger 2 tested 19 syntactic import patterns against `_find_forbidden_imports` and achieved 10 successful evasions:

| Evasion Vector | Root Cause in Existing Scanner | Real-World Risk |
|---|---|---|
| `from .api import x`<br>`from ..api import x` | Line 91: `and node.level == 0 and node.module` explicitly suppressed any relative from-import where `node.level > 0`. | Relative import bypassing host module ban. |
| `from .. import api`<br>`from . import api` | `node.module is None` when syntax is `from .. import x`. Scanner checked `node.module` and skipped inspecting `node.names`. | Relative package import bypassing ban. |
| `x = __import__(name='api')`<br>`x = importlib.import_module(name='api')` | Checked only positional argument `node.args[0]`. Completely ignored `node.keywords`. | Dynamic import bypassing ban via kwargs. |
| `x = builtins.__import__('api')` | Checked only `isinstance(node.func, ast.Name)`. Ignored attribute calls `builtins.__import__`. | Bypassing `__import__` detection. |
| `x = import_module('api')` | Checked only attribute calls `obj.import_module`. Ignored direct function call `import_module(...)`. | Bypassing `importlib.import_module` detection. |
| `\x61pi` / `\u0061pi` hex/unicode escapes | Line 76: `raw_bytes` byte pre-filter returned `[]` before calling `ast.parse`. | Escaped string bypass. |

### 2.2 Performance Feasibility of Removing Pre-filter
Benchmarking on the full set of 110 pure Python files (`PURE_DIRECTORIES` + `PURE_CONTEXT_FILES` + `PURE_UTILS_FILES`):
- Total files: **110 files**
- Parsing time without pre-filter: **60.75 ms**
- Required SLA threshold: **< 150.0 ms**
- Conclusion: Direct `ast.parse` parsing easily satisfies the performance requirement while providing complete immunity against lexical encoding evasions.

### 2.3 Watertight AST Scanner Implementation
Replace `_find_forbidden_imports` in `tests/test_import_boundaries.py` with the following implementation:

```python
def _find_forbidden_imports(file_path: Path) -> list[tuple[int, str, str]]:
	"""Parse a Python source file and return all forbidden NVDA import occurrences.

	Inspects:
	- Absolute imports: `import api`, `import api.sub as a`
	- Relative imports with module: `from .api import x`, `from ..api import x`
	- Relative imports without module: `from . import api`, `from .. import api`
	- Dynamic imports (positional and keyword): `__import__('api')`, `__import__(name='api')`,
	  `importlib.import_module('api')`, `import_module(name='api')`, `builtins.__import__('api')`

	Returns:
		List of tuples: (line_number, forbidden_module, code_snippet)
	"""
	text = file_path.read_text(encoding="utf-8", errors="replace")
	try:
		tree = ast.parse(text, filename=str(file_path))
	except SyntaxError:
		return []

	violations: list[tuple[int, str, str]] = []

	for node in ast.walk(tree):
		# 1. Direct import statement: `import api` or `import logHandler as log`
		if isinstance(node, ast.Import):
			for alias in node.names:
				root_pkg = alias.name.partition(".")[0]
				if root_pkg in FORBIDDEN_NVDA_MODULES:
					violations.append((node.lineno, root_pkg, f"import {alias.name}"))

		# 2. From-import statement: absolute AND relative (`node.level >= 0`)
		elif isinstance(node, ast.ImportFrom):
			dots = "." * node.level
			if node.module:
				root_pkg = node.module.partition(".")[0]
				if root_pkg in FORBIDDEN_NVDA_MODULES:
					violations.append(
						(node.lineno, root_pkg, f"from {dots}{node.module} import ...")
					)
			else:
				# Syntax: `from . import api` or `from .. import api, speech`
				for alias in node.names:
					root_pkg = alias.name.partition(".")[0]
					if root_pkg in FORBIDDEN_NVDA_MODULES:
						violations.append(
							(node.lineno, root_pkg, f"from {dots} import {alias.name}")
						)

		# 3. Dynamic import: `__import__(...)` or `importlib.import_module(...)`
		elif isinstance(node, ast.Call):
			is_import_call = False
			if isinstance(node.func, ast.Name) and node.func.id in ("__import__", "import_module"):
				is_import_call = True
			elif isinstance(node.func, ast.Attribute) and node.func.attr in ("__import__", "import_module"):
				is_import_call = True

			if is_import_call:
				mod_target: str | None = None
				if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
					mod_target = node.args[0].value
				elif node.keywords:
					for kw in node.keywords:
						if kw.arg == "name" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
							mod_target = kw.value.value
							break

				if mod_target:
					root_pkg = mod_target.partition(".")[0]
					if root_pkg in FORBIDDEN_NVDA_MODULES:
						violations.append(
							(node.lineno, root_pkg, f"dynamic import({mod_target!r})")
						)

	return violations
```

### 2.4 Verification against Adversarial Harness
Running the 19 test cases against this revised implementation achieves **19/19 (100%) detection rate**.

---

## 3. Focus Area 3: Investigation of the 3 Layer 0 Imports in Pure Packages

### 3.1 Exhaustive Catalog of All Relative Intra-Package Leaks
An empirical AST trace of all relative imports (`node.level > 0`) across all 110 pure domain files revealed that the only imports crossing into Layer 0 packages are:

| Source File | Line | Target Import | Resolved Target | Classification |
|---|---|---|---|---|
| `service/error_reporter.py` | 46 | `from ..ui import nvda_ui` | `ui.nvda_ui` | **FORBIDDEN** |
| `use_case/focus_image.py` | 12 | `from ..image import capture_focused_object` | `image.focus_capture` | **FORBIDDEN** |
| `use_case/focus_image.py` | 13 | `from ..image.services import ImageEncoder, ImagePreprocessor` | `image.services` | **FORBIDDEN** |
| `service/error_presentation.py` | 71 | `from ..image.screen_curtain import ScreenCurtainError` | `image.screen_curtain` | **FORBIDDEN** |
| `use_case/structure_summary.py` | 11 | `from ..context.navigation import build_llm_navigation_candidates` | `context.navigation` | **HYBRID MODULE** |
| `use_case/structure_summary_response.py` | 9 | `from ..context.navigation import NavigationTarget` | `context.navigation` | **HYBRID MODULE** |

---

### 3.2 Case 1: `service/error_reporter.py:46` (`from ..ui import nvda_ui`)

#### Observation & Mechanism
In `service/error_reporter.py`:
```python
class ErrorReporter:
	def __init__(self, notify: Callable[[str], None] | None = None) -> None:
		self._notify = notify or self._default_notify

	@staticmethod
	def _default_notify(message: str) -> None:
		try:
			from ..ui import nvda_ui
			nvda_ui.queue(nvda_ui.message, message)
		except Exception:
			log.exception("Unable to deliver global AI Assistant error notification")

error_reporter = ErrorReporter()
```

#### Assessment: **FORBIDDEN**
- **Violation of Hexagonal Architecture**: `service/` is an inner core domain layer. `ui/` is an outer delivery adapter. An inner core layer must never import an outer adapter surface.
- **Transitive Contamination**: `ui/nvda_ui.py` imports `queueHandler`, `ui`, `speech`, `tones`, and `logHandler`.
- In test environments or worker processes without NVDA, `_default_notify` fails on `from ..ui import nvda_ui` with `ModuleNotFoundError: No module named 'queueHandler'`.

#### Concrete Fix: Injected Notifier Port Pattern
Follow the exact architectural pattern introduced for `register_language_resolver` in `config/settings.py`:

**Step 1: In `addon/globalPlugins/AI-assistant/service/error_reporter.py`**:
```python
_error_notifier: Callable[[str], None] | None = None


def register_error_notifier(notifier: Callable[[str], None] | None) -> None:
	"""Register the global error notification handler (called by Layer 0 adapter during startup)."""
	global _error_notifier
	_error_notifier = notifier


class ErrorReporter:
	"""Report errors to a contextual surface, or NVDA as a safe fallback."""

	def __init__(self, notify: Callable[[str], None] | None = None) -> None:
		self._custom_notify = notify
		self._seen: set[tuple[str, str]] = set()
		self._lock = threading.Lock()

	def _notify(self, message: str) -> None:
		if self._custom_notify is not None:
			self._custom_notify(message)
			return

		if _error_notifier is not None:
			try:
				_error_notifier(message)
			except Exception:
				log.exception("Unable to deliver global AI Assistant error notification via registered notifier")
		else:
			log.warning("No global error notifier registered: %s", message)
```
*Remove `from ..ui import nvda_ui` entirely.*

**Step 2: In `addon/globalPlugins/AI-assistant/plugin/application.py` (during plugin startup)**:
```python
from ..ui import nvda_ui
from ..service.error_reporter import register_error_notifier

# During AssistantApp.initialize():
register_error_notifier(lambda msg: nvda_ui.queue(nvda_ui.message, msg))

# During AssistantApp.terminate():
register_error_notifier(None)
```

---

### 3.3 Case 2: `use_case/focus_image.py:12-13` (`from ..image import capture_focused_object`)

#### Observation & Mechanism
In `use_case/focus_image.py`:
```python
from ..image import capture_focused_object
from ..image.services import ImageEncoder, ImagePreprocessor
...
capture = capture_focused_object(
	preprocessor=ImagePreprocessor(),
	encoder=ImageEncoder(),
	main_thread_executor=(
		context_pipeline.run_on_main_thread if context_pipeline is not None else None
	),
)
```

#### Assessment: **FORBIDDEN**
- **Direct Acceptance Failure**: Importing `use_case.focus_image` in clean Python without NVDA immediately crashes:
  ```
  ModuleNotFoundError: No module named 'logHandler'
  ```
  `focus_image.py:12` -> `image/__init__.py:4` -> `image/focus_capture.py:11` (`from logHandler import log`).
- **Violation of Invariants & `AGENTS.md`**:
  `AGENTS.md` mandates:
  > "NVDA object-model access is thread-affine: resolve page, focus, selection, and image snapshots on the NVDA event thread via `ui/nvda_ui.py` wrappers; keep network, model, download, and persistence work off that thread."
  > "Route feature behavior through `UseCaseEngine`, `ContextPipeline`, `LLMService`, `ProviderProxy`..."
- `DescribeFocusedImageUseCase` bypassed `ContextPipeline` and invoked the Layer 0 image adapter directly.
- Meanwhile, `context/types.py:237` **already defines** `FocusedElementImageRequest` and `context/collectors/image.py` **already handles** it!
- `use_case/image.py` (`ImageDescriptionUseCase`) correctly uses `extraction_intent=ExtractionIntent(requests=(ForegroundImageRequest(),))` and consumes the captured image from the pipeline.

#### Concrete Fix: Pipeline-Backed Intent Extraction
Align `use_case/focus_image.py` with `use_case/image.py`:

**Step 1: Update `spec` in `use_case/focus_image.py`**:
```python
from ..context.types import ExtractionIntent, FocusedElementImageRequest, ImageContext

class DescribeFocusedImageUseCase(UseCase):
	@property
	def spec(self) -> UseCaseSpec:
		return UseCaseSpec(
			id="describe_focused_image",
			description="Describe the currently focused NVDA object image.",
			extraction_intent=ExtractionIntent(requests=(FocusedElementImageRequest(),)),
			prompt_key="image_description",
			tools=(),
			requires_input=False,
			result_actions=True,
		)
```

**Step 2: Update `execute` in `use_case/focus_image.py`**:
Remove `from ..image import ...` entirely. Retrieve the `ImageContext` from `prompt_context`:
```python
		# Execute prompt flow using standard pipeline-provided image context
		return self.execute_prompted_use_case(
			context_pipeline=context_pipeline,
			llm_service=llm_service,
			build_prompt=lambda prompt_context: build_image_description_prompt(
				self._get_image_context(prompt_context),
				language=prompt_context.language,
			),
			llm_call=lambda prompt, prompt_context, stream_handler: llm_service.describe_image(
				image_base64=self._get_image_context(prompt_context).image_base64 or "",
				prompt=prompt,
				stream_handler=stream_handler,
			),
			...
		)
```

**Step 3: Fix `ScreenCurtainError` in `service/error_presentation.py:71`**:
`ScreenCurtainError` is currently defined in `image/screen_curtain.py:5`. Move its definition to `addon/globalPlugins/AI-assistant/core/errors.py`:
```python
class ScreenCurtainError(RuntimeError):
	"""Raised when a screen-based feature is requested while the screen curtain is active."""
```
In `image/screen_curtain.py`, re-export `from ..core.errors import ScreenCurtainError`.  
In `service/error_presentation.py`, change:
```python
from ..core.errors import ScreenCurtainError
```
This purges all `..image` imports from `service/`.

---

### 3.4 Case 3: `use_case/structure_summary.py:11` (`from ..context.navigation import build_llm_navigation_candidates`)

#### Observation & Mechanism
`use_case/structure_summary.py:11` imports `build_llm_navigation_candidates`.  
`use_case/structure_summary_response.py:9` imports `NavigationTarget`.  
`context/structure_summary.py:232` imports `build_llm_navigation_candidates`.

Inspection of `context/navigation.py`:
- **Lines 1–554**: Pure Python data structures and ranking algorithms:
  - `NavigationTarget` (immutable dataclass)
  - `build_llm_navigation_candidates(...)`
  - `build_navigation_candidates(...)`
  - `select_navigation_targets(...)`
  - Scoring, ranking, TF-IDF / term overlap matching, cosine similarity.
  - **Zero NVDA imports. Zero Windows API imports.**
- **Lines 555–676**: NVDA tree-interceptor navigation execution:
  - `_tree_interceptor(...)` (calls `api.getFocusObject`)
  - `_restore_browser_focus(...)` (calls `winUser.setForegroundWindow`, `winUser.setFocus`)
  - `resolve_and_move_target(...)` (calls `import textInfos`)
  - The **only caller** of `resolve_and_move_target` in the entire codebase is `plugin/presenter.py:589`!

#### Assessment: **HYBRID MODULE / REFACTORING REQUIRED**
- The symbols imported by `use_case/` (`NavigationTarget`, `build_llm_navigation_candidates`) are purely functional algorithms that can run anywhere.
- However, combining pure data structures with NVDA-coupled action execution in `context/navigation.py` forced:
  1. `context/navigation.py` to be excluded from `PURE_CONTEXT_FILES`.
  2. `context/navigation.py` to be granted a `TID251` exception in `pyproject.toml:119`.
- Pure packages importing `from ..context.navigation` appear to import a file that contains `winUser` and `textInfos`.

#### Concrete Fix: Separate Pure Domain Algorithms from Layer 0 Navigation Execution
Decompose `context/navigation.py` into pure and adapter layers:

1. **Pure Domain File: `addon/globalPlugins/AI-assistant/context/navigation.py`**:
   - Retain `NavigationTarget`, `build_llm_navigation_candidates`, `build_navigation_candidates`, and candidate selection/scoring algorithms (lines 1–554).
   - Add `navigation.py` to `PURE_CONTEXT_FILES` in `tests/test_import_boundaries.py`.
   - Remove `"addon/globalPlugins/AI-assistant/context/navigation.py"` from `TID251` ignores in `pyproject.toml`.
2. **Layer 0 Adapter File: `addon/globalPlugins/AI-assistant/plugin/browser_navigation.py`**:
   - Move lines 555–676 (`_tree_interceptor`, `_restore_browser_focus`, `_role_candidates`, `_node_label`, `resolve_and_move_target`) into `plugin/browser_navigation.py`.
   - Update `plugin/presenter.py:20`:
     ```python
     from .browser_navigation import resolve_and_move_target
     ```
   - For backward compatibility during migration, `context/navigation.py` can expose a deprecated re-export or alias if needed, but since `presenter.py` is the sole caller, updating `presenter.py` is completely clean.

---

## 4. Focus Area 4: `pyproject.toml` Banned-API Rules Parity

### 4.1 Missing Modules Catalog
Comparison between `FORBIDDEN_NVDA_MODULES` in `tests/test_import_boundaries.py` and `[tool.ruff.lint.flake8-tidy-imports.banned-api]` in `pyproject.toml`:

| Forbidden Module | In AST Test | In `pyproject.toml` | Usages in Addon Code | File Types |
|---|---|---|---|---|
| `logHandler` | Yes | Yes | `utils/clipboard.py`, `utils/logger.py` | Layer 0 (ignored) |
| `languageHandler` | Yes | Yes | None in pure domain | Injected resolver port |
| `api` | Yes | Yes | `plugin/*`, `ui/*`, `image/*`, `utils/clipboard.py` | Layer 0 (ignored) |
| `textInfos` | Yes | Yes | `context/navigation.py`, `context/extractors/*` | Layer 0 (ignored) |
| `controlTypes` | Yes | Yes | `context/extractors/*`, `ui/*` | Layer 0 (ignored) |
| `globalPluginHandler` | Yes | Yes | `plugin/controller.py` | Layer 0 (ignored) |
| `scriptHandler` | Yes | Yes | `plugin/controller.py` | Layer 0 (ignored) |
| `queueHandler` | Yes | Yes | `ui/nvda_ui.py`, `ui/host_renderer.py` | Layer 0 (ignored) |
| `gui` | Yes | Yes | `ui/*` | Layer 0 (ignored) |
| `wx` | Yes | Yes | `ui/*` | Layer 0 (ignored) |
| `speech` | Yes | Yes | `ui/nvda_ui.py` | Layer 0 (ignored) |
| `tones` | Yes | Yes | `ui/nvda_ui.py` | Layer 0 (ignored) |
| **`addonHandler`** | Yes | **MISSING** | `plugin/__init__.py`, `plugin/application.py`, `ui/settings_panel.py` | Layer 0 (ignored) |
| **`globalVars`** | Yes | **MISSING** | None in codebase | Host runtime |
| **`winUser`** | Yes | **MISSING** | `image/focus_capture.py`, `context/navigation.py` | Layer 0 (ignored) |
| **`locationHelper`** | Yes | **MISSING** | `image/objects.py` | Layer 0 (ignored) |
| **`treeInterceptorHandler`** | Yes | **MISSING** | `context/extractors/browser*.py` | Layer 0 (ignored) |
| **`nvwave`** | Yes | **MISSING** | None in codebase | Host audio |

### 4.2 Exact Configuration Changes in `pyproject.toml`
Add the 6 missing modules to `[tool.ruff.lint.flake8-tidy-imports.banned-api]`:

```toml
[tool.ruff.lint.flake8-tidy-imports.banned-api]
"logHandler".msg = "Use standard library 'logging.getLogger(__name__)' instead of NVDA logHandler."
"languageHandler".msg = "Access language via injected LanguageResolver port."
"api".msg = "NVDA api access is forbidden outside Layer 0 adapter surfaces."
"textInfos".msg = "textInfos is forbidden outside Layer 0 adapter surfaces."
"controlTypes".msg = "controlTypes is forbidden outside Layer 0 adapter surfaces."
"globalPluginHandler".msg = "globalPluginHandler is forbidden outside plugin/controller.py."
"scriptHandler".msg = "scriptHandler is forbidden outside plugin/controller.py."
"queueHandler".msg = "queueHandler is forbidden outside ui/nvda_ui.py and ui/host_renderer.py."
"gui".msg = "gui is forbidden outside ui/ dialogs."
"wx".msg = "wx is forbidden outside ui/ dialogs."
"speech".msg = "speech is forbidden outside ui/nvda_ui.py."
"tones".msg = "tones is forbidden outside ui/nvda_ui.py."
"addonHandler".msg = "addonHandler is forbidden outside Layer 0 plugin/controller.py and ui/ panels."
"globalVars".msg = "globalVars is forbidden outside Layer 0 adapter surfaces."
"winUser".msg = "winUser is forbidden outside Layer 0 adapter surfaces."
"locationHelper".msg = "locationHelper is forbidden outside Layer 0 adapter surfaces."
"treeInterceptorHandler".msg = "treeInterceptorHandler is forbidden outside Layer 0 extractors."
"nvwave".msg = "nvwave is forbidden outside Layer 0 audio adapter surfaces."
```

### 4.3 Validation
Because all existing usages of `addonHandler`, `winUser`, `locationHelper`, and `treeInterceptorHandler` reside inside directories/files already covered by `[tool.ruff.lint.per-file-ignores]` (`ui/**`, `image/**`, `plugin/**`, `context/extractors/**`, `context/navigation.py`), running `uv run ruff check .` with these 6 rules active yields **0 lint errors**.

---

## 5. Architectural Test for Layer 0 Isolation

To prevent future developers from introducing relative imports into Layer 0 packages (`ui`, `image`, `plugin`), we recommend adding an explicit layer boundary test to `tests/test_import_boundaries.py`:

```python
FORBIDDEN_LAYER0_PACKAGES: frozenset[str] = frozenset({
	"ui",
	"image",
	"plugin",
})


def _resolve_relative_import_targets(file_path: Path, node: ast.ImportFrom) -> list[str]:
	"""Resolve relative import targets to their canonical package parts under ADDON_ROOT."""
	rel = file_path.relative_to(ADDON_ROOT)
	pkg_parts = list(rel.parent.parts)
	drop = node.level - 1
	base_parts = pkg_parts[: len(pkg_parts) - drop] if drop <= len(pkg_parts) and drop > 0 else []

	if node.module:
		return [".".join(base_parts + node.module.split("."))]
	return [".".join(base_parts + [alias.name]) for alias in node.names]


def test_pure_packages_have_zero_layer0_adapter_imports() -> None:
	"""Assert that pure domain/service packages never import Layer 0 adapter packages (ui, image, plugin)."""
	violations: list[str] = []
	for dir_name in PURE_DIRECTORIES:
		target_dir = ADDON_ROOT / dir_name
		if not target_dir.is_dir():
			continue
		for py_path in sorted(target_dir.rglob("*.py")):
			try:
				tree = ast.parse(py_path.read_text(encoding="utf-8", errors="replace"), filename=str(py_path))
			except SyntaxError:
				continue
			for node in ast.walk(tree):
				if isinstance(node, ast.ImportFrom) and node.level > 0:
					for target in _resolve_relative_import_targets(py_path, node):
						root_target = target.partition(".")[0]
						if root_target in FORBIDDEN_LAYER0_PACKAGES:
							rel_path = py_path.relative_to(ADDON_ROOT).as_posix()
							violations.append(
								f"  {rel_path}:{node.lineno} -> forbidden Layer 0 import '{target}'"
							)

	assert not violations, (
		f"Found {len(violations)} Layer 0 adapter import(s) in pure packages:\n"
		+ "\n".join(violations)
	)
```

---

## 6. Step-by-Step Implementation Roadmap for Implementation Agents

| Step | Action Item | Affected Files | Expected Outcome |
|---|---|---|---|
| **1** | Update `pyproject.toml` banned-api | `pyproject.toml` | 18 banned host modules. `uv run ruff check .` passes with 0 errors. |
| **2** | Decouple `utils/__init__.py` | `addon/globalPlugins/AI-assistant/utils/__init__.py` | Lazy `safe_read_clipboard` export prevents transitive `logHandler` contamination. |
| **3** | Decouple `service/error_reporter.py` | `service/error_reporter.py`, `plugin/application.py` | Replace `from ..ui import nvda_ui` with `register_error_notifier`. Zero NVDA imports. |
| **4** | Decouple `use_case/focus_image.py` | `use_case/focus_image.py` | Use `FocusedElementImageRequest` and pipeline image context. Zero `..image` imports. |
| **5** | Decouple `ScreenCurtainError` | `core/errors.py`, `image/screen_curtain.py`, `service/error_presentation.py` | Move exception class to pure layer. Purges `..image` import from `service/`. |
| **6** | Split `context/navigation.py` | `context/navigation.py`, `plugin/browser_navigation.py`, `plugin/presenter.py` | Pure candidate selection stays in `context/`; NVDA actions move to `plugin/`. |
| **7** | Enhance `tests/test_import_boundaries.py` | `tests/test_import_boundaries.py` | Add `PURE_UTILS_FILES`, fix relative imports, remove pre-filter, add Layer 0 check. |
| **8** | Verify Gate | All test commands | All tests pass, 0 lints, standalone pure test execution succeeds. |
