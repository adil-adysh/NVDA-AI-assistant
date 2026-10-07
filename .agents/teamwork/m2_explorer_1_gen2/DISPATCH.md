## 2026-10-04T22:40:44Z
You are Milestone 2 Explorer 1 (Iteration 2) for NVDA AI Assistant Migration Slice 0 & Slice 1.
Your working directory is: D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m2_explorer_1_gen2

You MUST read the authoritative request file:
D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\ORIGINAL_REQUEST.md (specifically ## 2026-10-04T17:22:12Z)
and the project master specification:
D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\orchestrator_slice0_1_gen2\PROJECT.md

MANDATORY AUDIT CONTEXT:
The previous iteration FAILED the Forensic Audit with INTEGRITY VIOLATION.
You MUST read the full evidence report from the Forensic Auditor:
D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m2_auditor_1_gen2\handoff.md
And the reports from Challenger 1 and Reviewer 1:
D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m2_challenger_1_gen2\handoff.md
D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\m2_reviewer_1_gen2\handoff.md

Mission: Design a concrete, genuine fix strategy for test tier gating and conftest sibling decoupling.
Focus:
1. When sibling checkout is absent (`HAS_NVDA_CHECKOUT == False` or simulated via `NVDA_STANDALONE=1`), `uv run pytest -m "not nvda_integration"` must succeed cleanly with 0 collection errors and 0 test failures.
2. Investigate why 8 test files fail collection: `tests/architecture/test_use_case_flow.py`, `tests/config/test_yaml_store.py`, `tests/integration/test_chat_lifecycle.py`, `tests/plugin/test_background_provider_ready.py`, `tests/plugin/test_background_shutdown.py`, `tests/plugin/test_presenter_ui_actions.py`, `tests/providers/test_llama_provider.py`, `tests/ui/test_adapter_fallback.py`.
   Determine which belong to pure vs integration tiers, which should be marked with `pytestmark = pytest.mark.nvda_integration`, and what conftest collection hooks should do when NVDA is absent.
3. Investigate failures in `tests/ui/test_task_runner.py` and `tests/context/test_navigation.py::NavigationTests::test_resolution_uses_duplicate_occurrence` (missing `textInfos`).
4. Support deterministic standalone testing via `os.environ.get("NVDA_STANDALONE")` in `conftest.py`.

Deliver your findings and step-by-step fix recommendations in `analysis.md` in your working directory.
Send a completion message back when done.
