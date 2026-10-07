# Plan: Migration Slice 0 & Slice 1 Implementation

## Phase 0: Scope Survey & Feature Inventory
- Dispatch 3 Explorers:
  - Explorer 1 (Rust Runtime Supervisor: `runtime_supervisor/` - RS-01, RS-02, RS-03, RS-04, RS-06, RS-10, `tests.rs`)
  - Explorer 2 (Pure Python Test Boundary: `conftest.py`, logging facade/fallback, `tests/test_import_boundaries.py`, AST checks)
  - Explorer 3 (Baseline Test State & Verification Commands: `uv run ruff check .`, `uv run cargo test`, `cargo check`, `uv run pytest`)
- Synthesize findings into `PROJECT.md` Feature Inventory & Architecture Decomposition.

## Phase 1: Milestone 1 — Slice 0: Rust Runtime Supervisor Concurrency Hardening
- Iteration loop:
  - Explorers (3) deep dive on implementation plan and exact diffs
  - Worker (1) implements Rust fixes in `runtime_supervisor/src/` and updates tests
  - Reviewers (2) verify Rust correctness, thread safety, Windows Job Object, and absence of test shims
  - Challengers (2) empirically stress-test supervisor state machine, concurrent restart, crash recovery
  - Forensic Auditor (1) checks integrity & authenticity
  - Gate evaluation: 100% approval, cargo test passes cleanly

## Phase 2: Milestone 2 — Slice 1: Pure Python Test Boundary Decoupling & Import Enforcement
- Iteration loop:
  - Explorers (3) map exact logging imports and design clean fallback facade + AST test
  - Worker (1) refactors `conftest.py`, implements logging fallback, adds `tests/test_import_boundaries.py`, updates `pyproject.toml`
  - Reviewers (2) review boundary decoupling, absence of forbidden imports, and `pytest -m "not nvda_integration"`
  - Challengers (2) test import boundaries across all pure packages and verify execution without `../nvda` checkout
  - Forensic Auditor (1) checks integrity & authenticity
  - Gate evaluation: 100% approval, AST test passes cleanly

## Phase 3: Milestone 3 — Integrated Zero-Regression Verification Gate
- Worker (1) executes full verification gate:
  - `uv run ruff check .` (0 errors)
  - `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml` (100% pass)
  - `cargo check --manifest-path nvda_ui_host/Cargo.toml` (clean)
  - `uv run pytest` (zero regression)
- Victory Forensic Auditor (1) runs comprehensive audit across all touched files.
- Final synthesis and reporting back to parent orchestrator.
