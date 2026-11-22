# Operation ownership refactor

Approved approach: incrementally refactor command sessions, model lifecycle coordination,
and operation outcomes in the existing architecture. A full framework rewrite and isolated
symptom patches were considered; explicit state ownership addresses the reproduced races
without moving Python behavior into Rust or Svelte.

## Requirements

- Command sessions have explicit Idle, Commands, LoadingChoices and Choosing states.
  Every activation and dismissal invalidates old asynchronous delivery tokens. Only the
  NVDA adapter changes gesture bindings. Model/provider choices retain stable IDs and
  every choice is reachable through pagination. Closing or error delivery from an old
  lookup must never change a newer session. Application shutdown invalidates the session.
- Model lifecycle admission is shared per endpoint. Removal blocks new loads, cancels
  and drains conflicting work, stops only owned servers and commits catalog/config state
  consistently. Worker/native lifecycle remains authoritative; command acknowledgements
  stay bounded and status/stop stay responsive. Views do not own durable operations.
- Shared Succeeded/Failed/Cancelled outcomes drive both callbacks and diagnostics.
  View dismissal suppresses delivery separately from operation cancellation. Diagnostic
  adapters own settings/file IO; application execution receives an injectable port.
- Preserve translation, private-worker lazy startup, protocol boundaries, existing
  preset grammar, cache rules, retained results and NVDA event-thread affinity.
- Use deterministic regression tests under top-level tests with shared loaders.

## Validation

Exercise stale success/error/empty lookup, reactivation, pagination, removal during
startup, queued and running cancellation, normal return after cancellation, detach and
shutdown. Run focused tests, full Python tests, lint, build graph, and producer/consumer
tests for any worker/native changes. No release, push or external publication is requested.
