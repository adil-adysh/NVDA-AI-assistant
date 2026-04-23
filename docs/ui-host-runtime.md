# UI Host Runtime Design

## Purpose

This document defines the recommended runtime design for:

- the external Rust host executable
- named-pipe creation and ownership
- command and event delivery between Python and Rust
- startup, health, recovery, and shutdown behavior

The goal is to keep process supervision, transport, and application behavior separate so the UI host remains reliable as more interactive features are added.

## Design goals

- start one host process per NVDA session and reuse it
- avoid coupling pipe lifecycle to individual commands
- separate synchronous command flow from asynchronous event flow
- make readiness and failure states explicit
- keep protocol parsing out of process supervision code
- allow graceful fallback to native NVDA UI when the host is unavailable

## Runtime ownership

### Python owns

- locating the packaged host executable
- starting and stopping the host process
- supervising health and restart policy
- deciding when host usage should fall back to native NVDA UI
- command initiation and event handling on the add-on side

### Rust owns

- creating and listening on named pipes
- accepting client connections
- reading and writing framed messages
- translating raw transport input into typed protocol handling
- forwarding typed UI work to the window and WebView layers

### The transport layer owns only

- pipe names and connection mode
- message framing
- bounded retries and timeouts
- delivery of bytes to the protocol layer

It must not own use-case semantics, provider decisions, or renderer-specific business rules.

## Host executable lifecycle

### Process model

Use one long-lived host executable for the NVDA session rather than spawning a process per command.

Benefits:

- lower latency after first launch
- simpler UI state ownership
- fewer startup races
- easier support for chat and interactive UI sessions

### Recommended process state machine

The Python supervisor should model host state explicitly:

1. `stopped`
2. `starting`
3. `ready`
4. `unhealthy`
5. `stopping`

Meaning:

- `stopped`: no running host process is owned
- `starting`: process spawn has begun but readiness is not confirmed
- `ready`: process is alive and the command pipe has passed readiness checks
- `unhealthy`: process exists but health or transport guarantees are no longer trusted
- `stopping`: shutdown is in progress and new commands should not be accepted

This avoids inferring host health from a single pipe operation.

### Readiness contract

A spawned EXE is not considered ready merely because `Popen` succeeded.

The host should be considered ready only when all of the following are true:

- the process is still alive
- the command pipe is reachable
- a health-check command succeeds

This is the correct boundary between process supervision and transport availability.

### Restart and recovery policy

The supervisor should use bounded recovery rather than unbounded restart loops.

Recommended behavior:

1. detect host failure or failed readiness
2. mark the host unavailable
3. perform one controlled restart attempt
4. if restart fails, fall back to native NVDA UI until the next explicit host use attempt

Avoid infinite respawn loops because they make NVDA unstable and noisy.

### Shutdown behavior

On add-on unload or NVDA shutdown:

1. stop accepting new host commands
2. request a host close if possible
3. terminate the process if it does not exit promptly
4. clear process handles and readiness state

This prevents orphaned host processes and stale pipe expectations.

## Named-pipe design

### Logical channels

The preferred long-term shape is two logical channels:

1. command channel: Python to Rust, request/response only
2. event channel: Rust to Python, asynchronous only

Recommended pipe names:

- `\\.\pipe\nvda_ai_assistant_ui_cmd`
- `\\.\pipe\nvda_ai_assistant_ui_evt`

If the implementation temporarily uses a single command pipe, asynchronous events should be handled through explicit polling rather than by assuming a long-lived duplex request connection.

### Why command and event channels should be separate

Command messages such as `render_display` and `open_chat` are short-lived and naturally fit request/response.

Event messages such as these are asynchronous by nature:

- `chat_submitted`
- `ui_applied`
- `ui_failed`
- `ui_action_invoked`
- `provider_selected`
- `model_selected`
- `window_closed`

Trying to force both flows through one transient synchronous connection makes the transport harder to reason about and harder to scale.

### Pipe creation rules

Rust should:

- create named-pipe instances as needed
- avoid first-instance-only flags when multiple sequential instances are expected
- keep raw pipe handling in the IPC layer only
- treat broken connections as transport events, not protocol failures

Python should:

- wait for pipe availability with bounded timeout
- treat connection timeout separately from protocol errors
- avoid holding application state inside transport objects

### Framing rules

Use a simple message framing contract that is easy to debug.

Recommended framing:

- UTF-8 JSON messages
- one logical message per line
- explicit newline terminator

Benefits:

- easy logging
- easy manual probing
- easy protocol fixture reuse across Python and Rust

## Division of responsibilities

### Process supervisor

`addon/globalPlugins/AI-assistant/ui/host_process.py` should own:

- executable path resolution
- one-time spawn and reuse
- readiness wait
- bounded restart policy
- shutdown and cleanup

It should not own protocol parsing or command semantics.

### Python transport

`addon/globalPlugins/AI-assistant/ui/host_transport.py` should own:

- connecting to the correct pipe
- sending framed bytes
- reading framed replies or polled events
- timeouts and connection-level retries

It should not own UI logic, conversation logic, or provider logic.

### Rust IPC layer

`nvda_ui_host/src/ipc.rs` should own:

- named-pipe creation
- connection acceptance
- message read and write loops
- handing off payloads to the protocol and app layers

It should not decide what commands mean.

### Rust app layer

`nvda_ui_host/src/app.rs` should own:

- parsing protocol messages into typed commands
- returning `ack` or `error`
- dispatching valid work to the UI thread

This is where transport becomes application-aware, but it still remains independent of WebView implementation details.

## How the runtime design affects use cases

### One-shot render flows

Examples:

- page summary
- structure summary
- image description
- error and progress display

These primarily need:

- reliable EXE startup
- low-latency command delivery
- clear fallback when the host is unavailable

They work well with the command channel alone.

### Chained result flows

Examples:

- image description followed by `Open Chat`
- summary followed by `Ask follow-up`

These need:

- result actions rendered by the UI
- a typed event path back to Python

They are where the boundary between command flow and event flow becomes important.

### Interactive session flows

Examples:

- open chat
- open chat with page content
- open chat with screenshot
- provider or model changes inside the UI

These need:

- a stable long-lived EXE
- explicit session ownership on the Python side
- asynchronous event delivery from the host UI back to Python

This is why chat should drive the long-term runtime design rather than summary-style rendering alone.

## Operational guidance

### Logging

Keep logging separated by concern:

- process supervisor logs on the Python side
- transport logs on both sides
- protocol parse and dispatch logs in Rust app logic
- UI rendering logs in WebView code when necessary

This makes it easier to distinguish startup failures, transport failures, and UI failures.

### Timeouts

Use bounded timeouts for:

- readiness wait
- pipe connect
- command response wait
- graceful shutdown wait

Timeout values should be long enough for slow startup but short enough to preserve NVDA responsiveness.

### Fallback policy

When host use fails, the add-on should:

1. record the failure
2. mark the host temporarily unavailable for that operation
3. fall back to native UI where possible

The host is an optimization and capability layer, not a requirement for basic add-on operation.

## Summary

The recommended runtime design is:

- one supervised host EXE per NVDA session
- explicit readiness and health checks
- separate command and event channels
- transport-only pipe layers
- bounded restart and shutdown behavior
- protocol ownership outside process supervision

This design keeps the host reliable for simple render flows while still scaling to chat, follow-up actions, model selection, and other interactive UI features.
