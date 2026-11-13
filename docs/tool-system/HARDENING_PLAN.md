# Tool System Hardening Plan

## Baseline

- HEAD: `0ecd452` (`docs(tools): document architecture, migration and implementation plan`).
- Working tree initially contained an unrelated untracked `.superpowers/` directory; it is preserved.
- `uv sync --locked`: passed.
- `uv run ruff check .`: passed.
- `uv run pytest`: 1,232 passed, 2 skipped, 40 deselected.
- `uv run pytest tests/tools -q`: 75 passed.
- The previously reported full-suite baseline is independently confirmed.
- Draft 2020-12 reference: <https://json-schema.org/draft/2020-12/json-schema-validation> and <https://json-schema.org/draft/2020-12/json-schema-core>.
- `jsonschema==4.26.0` is available through an ephemeral `uv run --with` environment for differential checks; it is not a project or add-on dependency.
- Final full suite: `uv run pytest` — 1,260 passed, 2 skipped, 40 deselected.
- Final focused suite: `uv run pytest tests/tools -q` — 103 passed.
- `uv run ruff check .`, Rust host `cargo check`, supervisor `cargo test` (24 passed), Web UI build (passed), Web UI tests (49 passed), `uv run scons --dry-run`, and `uv run scons` all passed.
- Built `AIAssistant-0.14.0.nvda-addon` and inspected the archive: 1,031 entries; no tests, `test_*.py`, or `.pyc` files.
- Differential checks covered `$ref` siblings, conditionals, dependent-required, dependent-schemas, property names, contains cardinality, integer floats and multiple-of arithmetic. One observed mismatch was Python-float `0.3 multipleOf 0.1`: the reference library performs binary float arithmetic while the implementation follows Draft 2020-12 decimal mathematical semantics; this is documented as a reference limitation.
- Phase 3 follow-up: `minContains` and `maxContains` without `contains` are valid Draft 2020-12 keywords that have no effect. Removed a structural rejection and added a regression; null remains invalid when supplied as an actual keyword value.

## Findings

### H01 — JSON Schema semantics

- **Claim:** Preserved validation keywords may not constrain arguments, and invalid schemas may be accepted.
- **Actual implementation:** Addressed. Supported assertions include `$ref` sibling application, conditionals, dependent-required/schemas, property-name constraints, contains cardinality, numeric equality/integer semantics, and implemented schema keywords. `minContains`/`maxContains` without `contains` are preserved as valid no-op constraints. Unsupported unevaluated/dynamic reference vocabularies and recursive/external refs fail closed. `format` remains annotation-only by default; unknown keywords remain annotations.
- **Reproduction:** Regression coverage in `tests/tools/test_schema.py`; differential checks against the official Draft 2020-12 behavior passed on the listed cases, with the Python-float reference limitation noted above.
- **Impact:** An incomplete validator could otherwise accept arguments that violate a provider's advertised constraints.
- **Severity:** P0.
- **Recommended correction:** Implement the tractable assertion keywords; reject recognized unsupported assertion vocabularies (including unevaluated applicators and dynamic references) with an actionable registration error; validate numeric constraints and preserve `$ref` sibling semantics. Keep annotation-only `format` documented.
- **Tests:** Schema regression tests and ephemeral Draft 2020-12 differential cases.
- **Final disposition:** Fixed and validated. Residual limit: this is an explicit supported subset, not a complete Draft 2020-12 validator; unsupported assertion vocabularies are rejected.

### H02 — Complete result bounds

- **Claim:** Result limiting only bounds text blocks.
- **Actual implementation:** Addressed. Bounded JSON copying now limits total envelope bytes, blocks, block size, media, metadata, depth, text, cycles, and unsupported values. Oversized results collapse to a deterministic bounded structured error; deserialization re-applies the limits.
- **Reproduction:** Adversarial regression coverage in `tests/tools/test_executor.py`; round-trip and serialized envelope bounds pass.
- **Impact:** Unbounded provider results could consume memory, break serialization/persistence, or bypass intended result limits.
- **Severity:** P0.
- **Recommended correction:** Add deterministic byte, block, per-block, and nesting limits across normalization and the persisted envelope; retain the distinct model-context text cap. Reject an oversized/invalid envelope as a bounded structured failure.
- **Tests:** JSON, media, metadata, depth, block-count, cycles, serialization, and repository round-trip regressions.
- **Final disposition:** Fixed and validated.

### H03 — Snapshot and schema immutability

- **Claim:** Frozen dataclasses expose mutable nested values.
- **Actual implementation:** Addressed. Definition schemas, parameters, required values, metadata and annotation raw payloads are recursively frozen; serialization explicitly thaws copies. Canonical provider conversion accepts frozen mappings without dropping constraints.
- **Reproduction:** Nested mutation and canonical serialization regressions in `tests/tools/test_schema.py` and `tests/tools/test_provider_serialization.py` pass.
- **Impact:** Mutable snapshot data could let a caller change validation or authorization-relevant metadata without a new generation or fingerprint.
- **Severity:** P0.
- **Recommended correction:** Deep-freeze JSON-like metadata and schemas at definition boundaries and thaw only for explicit serialization/compatibility exports. Preserve read-only access and stable fingerprints.
- **Tests:** Nested schema, metadata, annotation mutation attempts; fingerprint stability; generation changes.
- **Final disposition:** Fixed and validated. Python callers can still deliberately reach private internals; this is API hardening within one process, not a sandbox.

### H04 — Result normalization boundary

- **Claim:** Invalid backend results can escape as exceptions rather than structured tool failures.
- **Actual implementation:** Addressed. Normalization/finalization is guarded and unexpected errors are logged while callers receive bounded generic failures; classified tool errors retain category/correlation.
- **Reproduction:** Unsupported, cyclic and oversized provider values return structured failures with preserved call identity.
- **Impact:** Escaping normalization errors could abort a chat/tool loop and prevent a valid error result from being persisted.
- **Severity:** P0.
- **Recommended correction:** Make normalization/finalization failures become bounded `execution_error` results with preserved tool-call correlation; log unexpected internal exceptions with traces without returning internal details to the model.
- **Tests:** Unsupported types, invalid result envelopes, cyclic payloads, persistence after failure, correlation ID.
- **Final disposition:** Fixed and validated.

### H05 — Live revocation

- **Claim:** Old snapshots can still execute after provider disablement or approval revocation.
- **Actual implementation:** Addressed. Registry dispatch checks live provider/tool availability under the registry lock immediately before thread start; policy replacement is synchronized and signals active newly-denied calls. Provider refresh preserves a disabled provider state until explicit re-enable.
- **Reproduction:** Old-snapshot disable, active cooperative cancellation, policy revocation, reapproval, and disabled-provider catalog-refresh regressions pass.
- **Impact:** Without a live gate, retained snapshots could start side effects after disablement; active calls need cooperative revocation signalling.
- **Severity:** P0 security.
- **Recommended correction:** Add an atomic live dispatch gate coordinated with provider disablement, a synchronized host policy replacement/revocation boundary, and cancellation signalling for active work where the backend cooperates. Ordinary catalog refresh must continue to preserve old binding identity and must not silently imply revocation.
- **Tests:** Old-snapshot disable, provider disable/start race, policy revocation/start race, cancellation of active cooperative backend, explicit reapproval.
- **Final disposition:** Fixed and validated. An already dispatched handler cannot be forcibly stopped; it receives cooperative cancellation and remains subject to bounded global admission.

### H06 — Global outstanding-operation bound

- **Claim:** Timed-out/cancelled threads can accumulate.
- **Actual implementation:** Addressed. A process-wide semaphore caps outstanding handler threads at eight, is held until worker exit, rejects new calls immediately at capacity, and signals cancellation on timeout/revocation.
- **Reproduction:** Deterministic saturation and cooperative cancellation tests pass.
- **Impact:** Repeated stalled tools could exhaust threads and resources across turns.
- **Severity:** P1 availability.
- **Recommended correction:** Use one process-wide bounded admission gate; reject immediately when full; release capacity only in the worker's `finally`; signal cooperative cancellation while accurately preserving unconfirmed termination.
- **Tests:** Saturation, retained capacity after timeout, slot release on completion, cooperative cancellation.
- **Final disposition:** Fixed and validated. Hung in-process handlers can occupy all eight slots indefinitely; isolation in a killable process remains outside scope.

### H07 — Direct registry execution

- **Claim:** `ToolRegistry.execute()` bypasses mandatory execution policy.
- **Actual implementation:** The public method directly invokes the binding and returns `str(result)` without validation, permission checks, budget, timeout, normalization, or diagnostics. Repository search found no production or test call sites beyond its own definition.
- **Reproduction:** Source inspection and `test_registry_exposes_no_direct_execution_bypass` pass.
- **Impact:** The removed direct execution method bypassed the sole intended policy boundary.
- **Severity:** P1 security.
- **Recommended correction:** Remove the unused method and document `ToolExecutor` as the supported entrypoint.
- **Tests:** Regression asserting no registry execution API; existing executor tests remain authoritative.
- **Final disposition:** Fixed and validated. `_invoke` and backend fields remain private Python implementation details.

### H08 — Regex resource safety

- **Claim:** Untrusted schemas can trigger catastrophic backtracking in Python `re`.
- **Actual implementation:** Addressed. A conservative subset rejects nested/ambiguous repetition, backreferences, lookarounds, excessive bounds, and caps pattern length plus candidate strings whenever matching is needed. Schema registration validates regexes; runtime errors become violations.
- **Reproduction:** Safe-pattern, nested repetition rejection, and bounded candidate tests pass.
- **Impact:** Unsafe patterns could hang a chat worker and malformed runtime patterns could silently pass.
- **Severity:** P1 availability/security.
- **Recommended correction:** Accept a documented safe subset, reject unsafe constructs at schema registration, and return explicit schema validation errors instead of treating runtime regex errors as matches. Do not use unbounded helper threads for timeouts.
- **Tests:** Safe common patterns, nested-quantifier and ambiguous repeated-alternative rejection, invalid pattern rejection.
- **Final disposition:** Fixed and validated. Python `re` is not a formal linear-time engine; the conservative accepted subset and bounded matched inputs reduce the attack surface.

## Implementation sequence

1. Add regression tests and implement schema, immutability, and regex fixes.
2. Bound result normalization and persisted envelopes.
3. Add live revocation, cancellation signalling, and global slot accounting.
4. Remove direct execution bypass and update architecture/migration documentation.
5. Run the documented cross-layer validation matrix and inspect the built package.

## Independent review at current HEAD

- Reviewed HEAD 70eaaba (feat(tools): add isolated rmcp feasibility prototype). Before follow-up edits, uv sync --locked and uv run ruff check . passed; 111 focused tool tests passed.
- The full-suite baseline at this same HEAD was recorded in the preceding validation as 1,268 passed, 2 skipped and 40 deselected. The historical 1,232-test baseline above refers to the earlier hardening starting point 0ecd452.
- Kept the Rust MCP prototype, unrelated host JavaScript edits and .superpowers/ working-tree content out of this hardening scope.
- Added failing regressions for mutation through list.append, mismatched $schema dialects, regex backtracking limits, invalid result envelope coercion/overflow and frozen union types. All now pass.
- A temporary, non-project jsonschema 4.25.1 dependency served as the Draft 2020-12 oracle; 25 curated schema-instance cases matched. No dependency or lockfile change was made.
- Reproduced regex risk in a subprocess: a? repeated 16 times plus a failing suffix against an 8,192-character candidate exceeded a 2-second timeout. The tightened safe profile rejects it at schema registration.

### Follow-up dispositions

- **H01:** Root $schema declarations now must identify Draft 2020-12; older/custom dialects fail with an actionable error rather than having dialect-specific assertions silently treated as annotations. Differential checks matched in 25 curated cases.
- **H02/H04:** Result envelope reads require a boolean ok, valid content block shapes and valid flags. Unrepresentable/invalid durations and invalid blocks become bounded execution_error results with correlation retained. The string "false" no longer becomes success.
- **H03:** FrozenList is now tuple-backed; invoking list.append against the exposed array raises and fingerprints stay stable. A regression also verifies union types remain enforced on the frozen definition schema.
- **H08:** The regex subset now rejects optional-quantifier explosion and mixing an unbounded quantifier with additional quantifiers; bounded work is capped at 256 with at most eight bounded quantifiers.

H05 and H06 remain supported by the existing live registry gate, cooperative cancellation and process-wide semaphore tests. H07 remains resolved: production has no ToolRegistry.execute() API or caller; execution goes through ToolExecutor.

Final validation counts and build/package results will be added after the complete matrix finishes.

## Final validation at current HEAD plus hardening changes

- uv sync --locked: passed.
- uv run ruff check .: passed.
- uv run pytest tests/tools -q: 116 passed.
- uv run pytest: 1,273 passed, 2 skipped, 40 deselected (1,275 selected).
- cargo check --manifest-path nvda_ui_host/Cargo.toml: passed.
- PYO3_PYTHON=.venv/Scripts/python.exe cargo test --manifest-path runtime_supervisor/Cargo.toml: 24 passed.
- npm --prefix nvda_ui_host run build:webui: passed; npm --prefix nvda_ui_host run test:webui: 49 passed.
- uv run scons --dry-run and uv run scons: passed. The generated AIAssistant-0.14.0.nvda-addon contains 1,031 entries and no tests, test_*.py files or .pyc files.
- NVDA integration-marked tests were not run; they require the built NVDA checkout/process described in docs/development.md. The normal suite deselected 40 such tests.

The final audit confirms the bounded Python tool system is safe to proceed toward a future Rust MCP provider, subject to the documented limitations: unsupported schema vocabularies/dialects are rejected, Python regex support is deliberately conservative, in-process handlers cannot be forcibly terminated, and external tools still require host approval.
