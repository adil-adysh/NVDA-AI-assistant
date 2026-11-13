# Tool system hardening — implementation plan

Status: in progress. Source of truth for decisions, task state and verification
evidence for T01–T07. This plan is superseded only by `ARCHITECTURE.md` for the
final design.

Baseline before this work (main @ `8864b64`):

- `uv run pytest` → 1155 passed, 2 skipped, 40 deselected.
- `uv run ruff check .` → clean.

## Task state

| Task | State | Notes |
|---|---|---|
| T01 Repair chat tool calling | complete | Registry snapshot now reaches `ChatCoordinator` from the Python layer. |
| T02 Canonical tool schema | complete | Full JSON Schema, structural + argument validation, deterministic serialization. |
| T03 Dynamic registry | complete | Provider catalogs, generations, immutable snapshots, name mapping. |
| T04 Structured execution | complete | Structured result, error taxonomy, bounded content, persistence. |
| T05 Coordination/controls | complete | Policy, timeouts, cancellation, budgets, diagnostics. |
| T06 Tests | complete | `tests/tools/` plus updated chat integration tests. |
| T07 Docs/audit | complete | `ARCHITECTURE.md`, `MIGRATION.md`, security/concurrency review. |

## Decisions

### D1 — No new runtime dependency

`jsonschema` is not added. Its transitive `rpds-py` dependency is a native wheel
that would have to be vendored into `addon/.../lib` and loaded inside NVDA,
which is exactly the class of native packaging risk this milestone must avoid.
Instead `tools/schema.py` implements the draft 2020-12 subset that tools and
MCP servers actually use (objects, arrays, enums, `const`, `$defs`/`$ref`,
`anyOf`/`oneOf`/`allOf`, numeric/string/array bounds, `additionalProperties`).
Unknown keywords are preserved verbatim; only structurally invalid schemas are
rejected. See `docs/tool-system/ARCHITECTURE.md` § JSON Schema support.

### D2 — Immutable metadata, external handlers

`ToolDefinition` is frozen metadata (identity, names, schemas, annotations,
availability). Execution callables are stored in registry-owned `ToolEntry`
records / bindings, never in serialized definitions. A legacy `executor` field is
still accepted by the constructor and promoted into the registry entry at
registration; catalog snapshots strip it.

### D3 — Snapshot binding

Every catalog mutation publishes a new immutable `ToolCatalogSnapshot` with a
monotonic generation. A chat turn resolves one snapshot before the first model
request and passes it through `ChatCoordinator` → `ProviderLLMService` →
`ToolExecutor`. Each tool call resolves a `ToolBinding` in that snapshot; a
refresh that happens mid-turn cannot redirect an already-resolved call because
the binding carries the executor/backend captured at resolution time. Removed
tools are absent from later snapshots, so new requests cannot invoke them.

### D4 — Naming

Model-facing names must match `^[A-Za-z0-9_-]{1,64}$`. Native tools keep their
declared name when valid. External tools are deterministically namespaced as
`mcp_<provider>__<sanitized original>` with a short SHA-256 suffix when
truncation or sanitisation would collide. The binding retains the original
provider tool name, which makes the mapping reversible.

### D5 — Default permission policy

Until a permission UI exists, `DefaultToolPermissionPolicy` allows only native
tools annotated `read_only_hint=True`, plus tools/providers explicitly listed in
the approval sets held by the host. External tool metadata (names, descriptions,
annotations) is never consulted for authorization.

### D6 — Sync facade over bounded async-capable execution

The conversation stack stays synchronous. `ToolExecutor` keeps its synchronous
API; timeout enforcement runs the handler on a short-lived daemon thread and
joins it with a deadline. Cancellation is cooperative and reported distinctly
from confirmed termination (`termination_confirmed`).

### D7 — Provider adapters unchanged in shape

`core.canonical.Tool` gains optional full-schema fields so existing
`LLMProvider.generate(messages, tools)` implementations keep working while
OpenAI-compatible and Ollama serializers emit the complete schema. Tool results
keep the bounded model-visible text in `Part.text`; the structured envelope is
persisted in `Part.tool_result`.

### D8 — Budgets

The existing five-step tool loop (`ProviderLLMService.MAX_TOOL_STEPS`) is kept.
`ToolExecutionBudget` adds separate caps for total calls, per-call timeout,
turn duration, parallel calls (1 by default) and result size.

## Test plan

- `tests/tools/test_schema.py` — schema acceptance/rejection, `$defs`/`$ref`,
  immutability, deterministic serialization, argument validation.
- `tests/tools/test_registry.py` — register/unregister/update, provider
  catalogs, atomic replacement, collisions, concurrent access, in-flight
  binding during refresh, availability.
- `tests/tools/test_executor.py` — success, raising tool, invalid and malformed
  arguments, unknown tool, denied permission, timeout, cancellation, uncertain
  outcome, large output, structured result.
- `tests/tools/test_chat_tool_integration.py` — deterministic provider invoking
  `get_time` through `ChatCoordinator`, multi-call, streaming and non-streaming,
  persistence/reload, conversation switching, provider without tools, max steps.
- `tests/tools/test_provider_contract.py` — fake MCP-style providers: duplicate
  original names across servers, disconnected provider, refresh vs in-flight
  call, provider error mapping, untrusted metadata.

## Progress log

- 2026-11-13: baseline captured; main fast-forwarded from working tree commits
  (`feat(worker)`, `feat(llama)`, `docs`).
- 2026-11-13: T01–T07 implemented; 77 new test cases in `tests/tools/` plus two
  adapter forwarding tests in `tests/ui/test_adapter_fallback.py`.
- 2026-11-13: full validation run (below); remaining risks recorded in
  `ARCHITECTURE.md` § 13.

## Verification (actual results)

Environment: Windows, Python 3.13 (`.venv`), local NVDA source checkout present.

| Command | Result |
|---|---|
| `uv sync --locked` | pass (resolved 20 packages) |
| `uv run ruff check .` | pass |
| `uv run pytest` | **1232 passed, 2 skipped, 40 deselected, 60 subtests passed** (82 s) |
| focused: `uv run pytest tests/tools -q` | **75 passed** |
| focused: `uv run pytest tests/ui/test_adapter_fallback.py -q` | **25 passed** |
| `cargo check --manifest-path nvda_ui_host/Cargo.toml` | pass |
| `cargo test --manifest-path runtime_supervisor/Cargo.toml` (with `PYO3_PYTHON=.venv/Scripts/python.exe`) | **24 passed** |
| `uv run scons --dry-run` | pass |
| `uv run scons` | pass — produced `AIAssistant-0.14.0.nvda-addon` |

Not executed:

- `uv run pytest -m nvda_integration` (requires a recursively initialized and
  built NVDA checkout; not available in this environment).
- Desktop WebView2 manual dismissal test (`docs/development.md`): no native
  focus/hiding behavior was changed by this milestone.
- `NVDA_AI_REQUIRE_PACKAGED_TESTS=1` worker smoke tests: not a release build
  task; the package build itself passed.

Total test delta: baseline 1155 passed → 1232 passed (+77).

