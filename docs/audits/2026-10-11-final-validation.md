# Final validation and cleanup

The combined changes package the private CPython worker, add independent local
startup policies, repair settings and Web UI wiring, implement request cancellation,
correct host focus/dismissal, and add one-shot output preferences and retained results.
Readiness announcements describe a readiness check rather than claiming a new
server launch. Progress templates and the stopped-answer marker use gettext;
the generated POT includes the new settings and runtime messages.

Validation on Windows:

- Python: 902 tests and 60 subtests passed; two skips and 18 excluded NVDA
  integration tests. Ruff passed. Mandatory packaged smoke/path/watchdog: nine passed.
- Rust host: 42 unit tests, plus the real WebView2 dismissal/reopen test.
- Rust supervisor: 20 tests using the locked Python 3.13 interpreter.
- Web UI: 40 regressions and successful production build.
- SCons package and gettext catalog generation.

The desktop test waits for foreground restoration, because Windows may briefly
report a null foreground handle after hiding the host. This wait does not change
production focus policy.

Removed obsolete `.agents/teamwork` dispatch artifacts from the repository into
a recoverable local archive. Source, tests, audit reports, requirements, build
dependencies, and the latest installable package are retained. Generated English
documentation remains ignored; the root README is authoritative.

Live NVDA behavior after installation and the excluded NVDA integration tier are
separate from these automated checks. The translation catalog is generated;
language translations still need translators to supply localized text.
