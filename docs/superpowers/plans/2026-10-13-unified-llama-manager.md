# Implementation plan

Status: implementation and automated verification complete. Independent review
findings fixed with reproductions: offline HF cache reuse, replaced-file cache
token invalidation, honest companion compatibility after edits, and retained edit
drafts. Request-level seed is opt-in for llama generation and Use default removes
old pins while preserving thinking preferences.

Validation: 1,155 Python tests passed, two skipped; 40 NVDA integration tests passed;
Ruff/diff checks and SCons dry-run/full build passed. Required packaged-worker and
real installed router preset smoke: three passed, no skips. Artifact:
`AIAssistant-0.14.0.nvda-addon`. No commits created; prior dirty work preserved.
Live screen-reader/focus and real tensor compatibility remain manual release checks.

1. Add companion contracts/options and backward-compatible catalog serialization;
   worker HF artifact resolution/lazy companion download and model unload commands.
2. Add manager transactional create/edit APIs, dependency deletion protection,
   persistent operation registry, first-inference companion integration and shutdown.
3. Replace the three views with one list; add source/cache/HF picker and companion
   inputs; contextual More/Settings and persistent operation presentation.
4. Integrate boundary contracts, regressions and real-dialog flows; independent
   review; Ruff/full Python/NVDA integration/build/package/router smoke verification.

Tasks 1 and 3 have separate file ownership and explicit interfaces; the coordinator
owns Task 2 and integration. Existing tests with old navigation must be migrated
to verify the new journeys rather than retain obsolete controls. No unrelated reset.
