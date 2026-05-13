# Stream Projection Spec

> **Purpose**: Behavioral contract for streaming LLM response text from the Python addon to the Rust/WebView host UI.
> **Current location**: `_StreamedAssistantProjection` class in `ui/adapter.py` (lines ~38-170).
> **Target**: Extract to `ui/stream_projection.py`.

## Responsibilities

`StreamProjection` bridges the gap between LLM streaming callbacks and host protocol commands. It:

1. Normalizes partial text fragments from the LLM into a consistent running text.
2. Buffers delta chunks to avoid flooding the host with per-token updates.
3. Flushes deltas to the host using `chat_stream_begin` → `chat_stream_delta` commands.
4. Finalizes the stream with `chat_stream_end` (or `chat_stream_abort` on failure).
5. Falls back to `chat_append` when streaming never started (no deltas sent).

## Lifecycle

```
┌─────────┐  update()   ┌──────────┐  flush()    ┌───────────────┐
│  Created │ ──────────→ │ Buffering│ ──────────→ │ chat_stream_   │
│          │             │  deltas  │             │ begin (once)   │
└─────────┘             └──────────┘             │ delta (repeat) │
                                                  └───────────────┘
                                                         │
                                                    finish()
                                                         │
                                                  ┌──────┴──────┐
                                                  │ chat_stream_ │
                                                  │ end / abort  │
                                                  │ (or append)  │
                                                  └─────────────┘
```

## Input contract

### `update(partial_text: str, generated_chars: int) -> None`

Called by the LLM streaming callback. May be called many times with overlapping or incremental text.

Behavior:
- If `host_stream_updates_enabled` is False, no-op.
- Normalizes `partial_text` against previously seen text (`normalized_stream_text`) to extract only new content.
- Appends new text to `pending_stream_delta_chunks`.
- Flushes when pending char count >= `stream_update_interval` (default 1200), or on first call.

### `flush() -> bool`

Sends accumulated deltas to the host. Returns True if streaming started successfully.

Behavior:
- Concatenates all `pending_stream_delta_chunks`.
- On first flush: sends `chat_stream_begin(use_case_id, conversation_id, message_id, stream_id)`.
- On subsequent flushes: sends `chat_stream_delta(use_case_id, conversation_id, message_id, stream_id, delta, sequence)`.
- Increments `stream_sequence` after each successful delta.
- Clears pending chunks after send.
- If any send fails: sets `host_stream_updates_enabled = False`, clears pending, returns False.
- Plays NVDA streaming tone after each flush.

### `finish(assistant_content: list[dict[str, Any]]) -> None`

Called when LLM response is complete.

Behavior:
- Calls `flush()` one final time.
- If streaming was started: sends `chat_stream_end(use_case_id, conversation_id, message_id, stream_id, final_sequence, content, metadata)`.
- If streaming never started (no deltas sent): sends `chat_append(use_case_id, conversation_id, message)` with full content.
- On failure: sends `chat_stream_abort(use_case_id, conversation_id, message_id, stream_id, final_sequence, reason="final_commit_failed")` if streaming was started.

## Normalization algorithm

`_normalize_stream_fragment(known_text, partial_text, generated_chars)`:

1. If `partial_text` is empty → return `(known_text, "")`.
2. If `generated_chars <= len(known_text)` → no new content, return `(known_text, "")`.
3. If `len(partial_text) == generated_chars` → partial_text is the full response, return as-is.
4. If `known_length + len(partial_text) == generated_chars` → concatenate.
5. If `partial_text.startswith(known_text)` → slice to `generated_chars`.
6. Otherwise → concatenate and trim to `generated_chars`.
7. Extract delta: everything after `known_text` prefix.
8. Return `(normalized_text, delta_text)`.

## Constructor parameters

| param | type | description |
|-------|------|-------------|
| `renderer` | `HostRenderer` | Host command sender |
| `use_case_id` | `str \| None` | Originating use case |
| `conversation_id` | `str` | Active conversation |
| `message_id` | `str` | Assistant message ID |
| `stream_id` | `str` | Unique stream identifier |
| `final_metadata_factory` | `() -> dict` | Callable producing metadata for `chat_stream_end` |
| `stream_update_interval` | `int` (default 1200) | Character threshold for flush |

## Host protocol commands used

| command | when |
|---------|------|
| `chat_stream_begin` | First `flush()` call |
| `chat_stream_delta` | Each subsequent `flush()` with content |
| `chat_stream_end` | `finish()` when streaming was active |
| `chat_stream_abort` | `finish()` failure recovery when streaming was active |
| `chat_append` | `finish()` when streaming never started |

## Error handling

- Any host send failure → `host_stream_updates_enabled = False` for remaining lifetime.
- Finalization failure → abort if streaming was started, log and swallow otherwise.
- Backend response is preserved regardless of UI projection failure.
