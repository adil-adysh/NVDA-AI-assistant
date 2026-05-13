# Behavioral Specs

These specs describe the **current** behavior of key modules as contracts. They serve as:

1. **Safety nets** — validate refactored code produces identical behavior.
2. **Onboarding** — coding agents can read specs instead of full source files.
3. **Code generation targets** — `protocol-contract.md` is the canonical definition for generating Python/Rust/TypeScript protocol types.

## Specs

| Spec | What it covers | Target files |
|------|---------------|-------------|
| [protocol-contract.md](protocol-contract.md) | All commands, events, envelope rules, and presentation metadata | `host_protocol.py`, `protocol.rs`, `protocol-types.ts`, `bridge.ts` |
| [stream-projection.md](stream-projection.md) | Streaming text normalization, buffering, and host protocol commands | `adapter.py` → `stream_projection.py` |
| [presentation-intent.md](presentation-intent.md) | How Python expresses UI intent via typed metadata | `intent.py`, `presenter.py`, `adapter.py`, `app.rs` |

## When to update

- **Before** adding a new command or event → update `protocol-contract.md` first.
- **Before** extracting a class → create a behavioral spec (like `stream-projection.md`).
- **After** changing presentation intent semantics → update `presentation-intent.md`.
