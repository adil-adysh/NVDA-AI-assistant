## 2026-10-04T18:27:57Z

You are the Implementation Worker for Milestone 2 (Slice 1: Pure Python Test Boundary Decoupling & Import Enforcement).
Your working directory is: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m2_worker_1

You MUST read the authoritative request file first:
D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\ORIGINAL_REQUEST.md
and the project specification:
D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\orchestrator_slice0_1\PROJECT.md

Read the three Explorer analysis reports that provide the exact code designs and test architectures:
1. D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m2_explorer_1\analysis.md (Conftest sibling decoupling, integration test gating)
2. D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m2_explorer_2\analysis.md (utils/logger.py, 18 pure modules logging purge, config/settings.py language resolver)
3. D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m2_explorer_3\analysis.md (tests/test_import_boundaries.py, pyproject.toml TID251 config)

WRITE OWNERSHIP:
You exclusively own and may modify ONLY these files:
- conftest.py
- addon/globalPlugins/AI-assistant/utils/logger.py (create)
- addon/globalPlugins/AI-assistant/config/settings.py
- The 18 pure files to purge logHandler imports:
  addon/globalPlugins/AI-assistant/config/state.py
  addon/globalPlugins/AI-assistant/config/yaml_store.py
  addon/globalPlugins/AI-assistant/utils/crypto.py
  addon/globalPlugins/AI-assistant/service/base.py
  addon/globalPlugins/AI-assistant/service/model_cache.py
  addon/globalPlugins/AI-assistant/service/error_reporter.py
  addon/globalPlugins/AI-assistant/service/chat/coordinator.py
  addon/globalPlugins/AI-assistant/service/chat/repository_backends.py
  addon/globalPlugins/AI-assistant/providers/litert_manager.py
  addon/globalPlugins/AI-assistant/providers/llama_manager.py
  addon/globalPlugins/AI-assistant/providers/provider_proxy.py
  addon/globalPlugins/AI-assistant/providers/_provider_runtime.py
  addon/globalPlugins/AI-assistant/providers/adapters/openai_compat.py
  addon/globalPlugins/AI-assistant/providers/runtime/download.py
  addon/globalPlugins/AI-assistant/providers/runtime/manager.py
  addon/globalPlugins/AI-assistant/providers/runtime/model_download.py
  addon/globalPlugins/AI-assistant/prompts/base.py
  addon/globalPlugins/AI-assistant/observability/reporter.py
- tests/test_import_boundaries.py (create)
- pyproject.toml
- tests/integration/test_nvda_imports.py
- tests/context/extractors/test_browser_field_parser.py
- tests/context/test_browser_field_graph.py
- tests/config/test_settings_activation.py
- tests/providers/test_litert_manager.py

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

YOUR TASKS:
1. Conftest Sibling Decoupling (per m2_explorer_1):
   - Refactor root `conftest.py`: check `HAS_NVDA_CHECKOUT = (NVDA_SOURCE / "api.py").is_file()`. Only inject sys.path / globalVars if HAS_NVDA_CHECKOUT. Define builtins._ and REAL_NVDA_MODULES unconditionally. Add `pytest_collection_modifyitems` hook skipping `nvda_integration` tests when missing checkout.
   - In `tests/integration/test_nvda_imports.py`: add `pytestmark = pytest.mark.nvda_integration`.
   - In `tests/context/extractors/test_browser_field_parser.py`: guard `import controlTypes` with `try...except ImportError` and add `pytestmark = pytest.mark.nvda_integration`.
   - In `tests/context/test_browser_field_graph.py`: guard `load_module` with `try...except ImportError` and add `pytestmark = pytest.mark.nvda_integration`.
2. Logging & Language Decoupling (per m2_explorer_2):
   - Create `addon/globalPlugins/AI-assistant/utils/logger.py` with `NVDALogBridge(logging.Handler)` (including recursion guards, drop-bridged filter on logHandler, and codepath preservation).
   - In the 18 pure files listed above: replace `from logHandler import log` with standard `import logging; log = logging.getLogger(__name__)`.
   - In `addon/globalPlugins/AI-assistant/config/settings.py`: remove top-level `import languageHandler`, implement `register_language_resolver`, and update `get_effective_language()` to use resolver or fallback to `"en"`.
   - In `tests/config/test_settings_activation.py` and `tests/providers/test_litert_manager.py`: update to use `register_language_resolver(lambda: "en")`.
3. Automated AST Boundary Tests & Ruff TID251 (per m2_explorer_3):
   - Create `tests/test_import_boundaries.py` with AST-based boundary tests asserting 0 forbidden NVDA imports across pure packages and performance < 150ms.
   - Update `pyproject.toml`: add `TID251` to `extend-select`, configure `flake8-tidy-imports.banned-api` for forbidden NVDA modules, and configure `per-file-ignores` for adapter files (including `context/navigation.py`, `conftest.py`, and `utils/logger.py`).
4. Verification:
   - `uv run ruff check .` (0 errors)
   - `uv run pytest tests/test_import_boundaries.py` (3 passed in < 150ms)
   - `uv run pytest -m "not nvda_integration"` (451+ pure tests pass)
   - `uv run pytest` (all 461+ tests pass, 0 regressions)
   - `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml` (20 passed)
   - `cargo check --manifest-path nvda_ui_host/Cargo.toml` (0 errors)

Document your changes and test outputs in:
`D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m2_worker_1\changes.md`
and write your completion handoff report to:
`D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m2_worker_1\handoff.md`.
Notify orchestrator via `send_message`.
