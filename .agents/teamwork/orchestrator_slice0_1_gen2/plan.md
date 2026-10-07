# Plan — Project Orchestrator (Gen 2)

## Milestone 2: Slice 1 Review, Challenge, and Audit Gate
1. Dispatch 2 independent Reviewers (`teamwork_preview_reviewer`):
   - Reviewer 1: Conftest decoupling, test tier markings, standalone pure test execution (`pytest -m "not nvda_integration"`).
   - Reviewer 2: Logging facade & bridge (`utils/logger.py`), language resolver decoupling (`config/settings.py`), AST boundary tests (`tests/test_import_boundaries.py`), and Ruff `TID251` rules.
2. Dispatch 2 independent Challengers (`teamwork_preview_challenger`):
   - Challenger 1: Adversarially challenge test execution under simulated missing sibling checkout, testing that pure test modules run cleanly and integration tests properly skip.
   - Challenger 2: Adversarially challenge AST boundary verification by checking corner cases (relative imports, dynamic imports, package boundary coverage) and ruff banned APIs.
3. Dispatch 1 Forensic Auditor (`teamwork_preview_auditor`):
   - Perform forensic integrity checks on Slice 1 implementation: verify no fake tests, no circumvented boundary checks, no hardcoded stubs, no bypassing of NVDA dependencies.
4. Evaluate Milestone 2 Gate:
   - Check all Reviewer, Challenger, and Auditor verdicts in `GATE_STATUS.md`.
   - Ensure strict criteria: All pass, Auditor CLEAN.

## Milestone 3: Integrated Zero-Regression Verification Gate
1. Dispatch Worker / Verifier to run complete verification commands across both slices:
   - `uv run ruff check .`
   - `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml`
   - `cargo check --manifest-path nvda_ui_host/Cargo.toml`
   - `uv run pytest`
   - `uv run pytest -m "not nvda_integration"`
2. Verify all 16 features from `PROJECT.md` are completely accounted for.
3. Synthesize final `GATE_STATUS.md` and submit comprehensive completion report via `send_message` to parent (`d499e345-2e46-4f54-8287-bbfb8a90e1c3`).
