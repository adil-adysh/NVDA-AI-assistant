## 2026-10-04T22:55:05Z
You are Milestone 2 Remediation Worker for NVDA AI Assistant Migration Slice 0 & Slice 1.
Your working directory is: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m2_worker_1_gen2

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT
hardcode test results, create dummy/facade implementations, or
circumvent the intended task. A teamwork_preview_auditor will independently
verify your work. Integrity violations WILL be detected and your
work WILL be rejected.

You MUST read the authoritative request file:
D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\ORIGINAL_REQUEST.md (specifically ## 2026-10-04T17:22:12Z)
and the project master specification:
D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\orchestrator_slice0_1_gen2\PROJECT.md

You MUST read the Forensic Auditor report:
D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m2_auditor_1_gen2\handoff.md
And the Explorer analysis reports:
D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m2_explorer_1_gen2\analysis.md
D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m2_explorer_2_gen2\analysis.md
D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m2_explorer_3_gen2\analysis.md

Files you own exclusively:
- `addon/globalPlugins/AI-assistant/utils/__init__.py`
- `addon/globalPlugins/AI-assistant/utils/clipboard.py`
- `addon/globalPlugins/AI-assistant/utils/logger.py`
- `addon/globalPlugins/AI-assistant/plugin/application.py`
- `addon/globalPlugins/AI-assistant/plugin/presenter.py`
- `addon/globalPlugins/AI-assistant/plugin/background.py`
- `addon/globalPlugins/AI-assistant/ui/adapter.py`
- `addon/globalPlugins/AI-assistant/ui/task_runner.py`
- `conftest.py`
- `tests/context/test_navigation.py`
- `tests/test_import_boundaries.py`
- `pyproject.toml`

Implementation Tasks:
1. `addon/globalPlugins/AI-assistant/utils/__init__.py`:
   Remove `from .clipboard import safe_read_clipboard` from eager module scope (export only `render_markdown_to_html` or provide lazy `__getattr__` for non-breaking access), ensuring that importing `utils.crypto` does not eagerly trigger `clipboard.py`.
2. `addon/globalPlugins/AI-assistant/utils/clipboard.py`:
   Replace `from logHandler import log` with `import logging; log = logging.getLogger(__name__)`.
3. `addon/globalPlugins/AI-assistant/plugin/presenter.py`:
   Replace `from logHandler import log` with `import logging; log = logging.getLogger(__name__)`.
4. `addon/globalPlugins/AI-assistant/plugin/background.py`:
   Replace `from logHandler import log` with `import logging; log = logging.getLogger(__name__)`.
5. `addon/globalPlugins/AI-assistant/ui/adapter.py`:
   Replace `from logHandler import log` with `import logging; log = logging.getLogger(__name__)`.
6. `addon/globalPlugins/AI-assistant/ui/task_runner.py`:
   Replace `from logHandler import log` with `import logging; log = logging.getLogger(__name__)`.
7. `addon/globalPlugins/AI-assistant/utils/logger.py`:
   In `attach_nvda_log_bridge(logger_name: str | None = None) -> bool`, ensure `target_logger.setLevel(logging.DEBUG)` so debug/info records are dispatched to the bridge.
8. `addon/globalPlugins/AI-assistant/plugin/application.py`:
   In `AIAssistantApplication.__init__`, wire:
   ```python
   from ..utils.logger import attach_nvda_log_bridge
   attach_nvda_log_bridge()
   try:
       import languageHandler
       from ..config.settings import register_language_resolver
       register_language_resolver(languageHandler.getLanguage)
   except Exception:
       pass
   ```
9. `tests/context/test_navigation.py`:
   Decorate `NavigationTests.test_resolution_uses_duplicate_occurrence` with `@pytest.mark.nvda_integration`.
10. `conftest.py`:
   Update:
   `HAS_NVDA_CHECKOUT = not os.environ.get("NVDA_STANDALONE") and (NVDA_SOURCE / "api.py").is_file()`
   In `if not HAS_NVDA_CHECKOUT:`, install fallback standard-library-backed `logHandler` shim:
   ```python
   if "logHandler" not in sys.modules:
       import logging, types
       log_module = types.ModuleType("logHandler")
       log_module.log = logging.getLogger("nvda.fallback")
       log_module.logHandler = None
       sys.modules["logHandler"] = log_module
   ```
11. `tests/test_import_boundaries.py`:
   - Add `PURE_UTILS_FILES = ("crypto.py", "markdown.py", "mathml.py")`.
   - Add `test_pure_utils_modules_have_zero_forbidden_nvda_imports()`.
   - Update `_find_forbidden_imports` to inspect relative imports (`node.level >= 0`) properly.
12. `pyproject.toml`:
   - Add missing host modules to `tool.ruff.lint.flake8-tidy-imports.banned-api` (`addonHandler`, `globalVars`, `winUser`, `locationHelper`, `treeInterceptorHandler`, `nvwave`).
   - Ensure `per-file-ignores` allows Layer 0 adapter files appropriately.

Verification Commands to Run:
- `uv run ruff check .`
- `uv run pytest tests/test_import_boundaries.py`
- `uv run python -c "import pathlib, os, pytest; orig = pathlib.Path.is_file; pathlib.Path.is_file = lambda s: False if 'api.py' in str(s) else orig(s); raise SystemExit(pytest.main(['-m', 'not nvda_integration']))"`
- `uv run pytest -m "not nvda_integration"`
- `uv run pytest`
- `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml`
- `cargo check --manifest-path nvda_ui_host/Cargo.toml`

Document all changes in `changes.md` and complete a full 5-component handoff report (`handoff.md`) in your working directory. Send a completion message back when done.
