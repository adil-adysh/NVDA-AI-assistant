"""
Harrier Embedding Model Validation Suite.

Comprehensive real-world validation of the Rust/Candle Harrier implementation
against the official Hugging Face reference model.

Entry point::

    python -m tests.harrier.run_validation

This produces:
- ``harrier_validation_results.json`` — machine-readable results
- ``harrier_validation_report.md`` — human-readable report
"""

__version__ = "1.0.0"
