# Harrier Embedding Model — Validation Suite

Comprehensive real-world validation of the Rust/Candle Harrier embedding implementation
against the official [microsoft/harrier-oss-v1-270m](https://huggingface.co/microsoft/harrier-oss-v1-270m) model.

## Quick Start

```bash
# From the embedding_engine directory:
python -m tests.harrier.run_validation
```

The suite automatically:
1. Loads the HF reference model (via `sentence-transformers`)
2. Loads the Rust/Candle model (via `embedding_engine`)
3. Runs all 15 validation suites
4. Produces `harrier_validation_results.json` and `harrier_validation_report.md`

## Prerequisites

```bash
pip install sentence-transformers torch
```

The `embedding_engine` module must be built and importable:

```bash
maturin develop
```

## Test Suites

| Suite | Category | Description |
|-------|----------|-------------|
| 01 | Numerical Parity | HF vs Rust cosine/L2/max-abs across 80 inputs |
| 02 | Semantic Similarity | Positive, hard-negative, unrelated pairs |
| 03 | Retrieval | 50-doc collection, 30 queries, Recall@k, MRR, nDCG |
| 04 | Hard Negatives | Lexically similar but semantically different docs |
| 05 | Multilingual | 12 languages, cross-language pairs, retrieval |
| 06 | NVDA Real-World | Screen-reader text, StackOverflow, GitHub issues, logs |
| 07 | Long Context | 128–4096 token documents, position tests |
| 08 | Query/Document | Verifies instruction prefix behavior |
| 09 | Edge Cases | Empty, punctuation, code, emoji, stack traces |
| 10 | Determinism | 5 repeated runs, max difference check |
| 11 | Performance | Baseline latency and throughput |
| 12 | Failure Tests | Informational: where the model struggles |
| 13 | Ranking Consistency | HF vs Rust top-k overlap, Kendall tau |
| 14 | Threshold Calibration | Cosine distributions by relationship type |
| 15 | Regression | Tests for previously-fixed bugs |

## Output

- **`harrier_validation_results.json`** — Full machine-readable results with per-test metrics
- **`harrier_validation_report.md`** — Human-readable report with executive summary and failure details

## Test Status Codes

| Status | Meaning |
|--------|---------|
| `PASS` | Test passed (meets criteria) |
| `FAIL` | Test failed (requires investigation) |
| `WARNING` | Test produced suspicious result (may be benign) |
| `NOT_APPLICABLE` | Informational only (no pass/fail) |

## Acceptance Criteria

- [ ] HF/Rust numerical parity >= 0.9999 for normal inputs
- [ ] No NaN/Inf in any output
- [ ] Deterministic across repeated runs
- [ ] Long-context tests pass (including 513-token boundary)
- [ ] Multilingual tests pass
- [ ] Query/document behavior is correct
- [ ] Retrieval ranking is consistent with HF
- [ ] Hard negatives are handled reasonably
- [ ] NVDA-like noisy text works reasonably
- [ ] All regression tests pass
- [ ] No existing Granite/MiniLM regressions

## Important Notes

- The test suite does **NOT** modify the model implementation
- If a test fails, the failure is reported — do not tune thresholds until baseline is collected
- Performance tests are baseline measurements, not pass/fail
- Failure tests (suite 12) are informational — they document known model limitations
