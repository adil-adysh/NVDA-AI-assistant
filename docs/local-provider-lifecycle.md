# Managed local-provider lifecycle and cache contract

The llama.cpp and LiteRT-LM integrations both expose an OpenAI-compatible
endpoint, but they do not share a runtime implementation or cache identity.

## llama.cpp

`LlamaCppModelManager.ensure_running()` lazily starts the server before a
request. `LlamaServerSupervisor` owns the child process, readiness polling,
and server model-catalog cache. Supervisors are cached by normalized
executable path, case-insensitive host, and port.

A live owned server is reusable only when its immutable startup snapshot still
matches. For router mode the snapshot is the preset's normalized path and
content digest, thread count, and context size. Model selection is deliberately
absent because it is carried by each request. For single-model mode the model
identity is also part of the snapshot. Starting, adopting, and stopping clear
the server model-catalog cache. Application shutdown stops and evicts every
cached supervisor.

## LiteRT-LM

`ensure_litert_server_ready()` lazily starts or adopts the application-wide
`LiteRTServerSupervisor`. The supervisor owns the child process and readiness;
LiteRT-LM itself owns lazy model loading inside that process.

The process startup snapshot contains the bundled runtime version and Python
path, host, port, and the complete generated engine `config.json` payload.
That payload includes context/KV-cache size, backend, cache policy, CPU thread
count, and any per-model values written to LiteRT-LM's server configuration.
A live process whose snapshot differs is stopped and replaced before use.
The configuration is snapshotted once and the exact snapshot is written before
spawn, preventing mutable settings from changing the meaning of a cache entry.

## State transitions

Both supervisors implement these observable states without persisting a state
enum:

```text
STOPPED -> STARTING -> RUNNING -> READY
              |          |         |
              +-> FAILED +-> DEAD  +-> STOPPED
```

The lifecycle lock serializes startup and shutdown. A failed spawn never
publishes a process or startup identity. A readiness timeout stops an owned
process. An exited process fails `is_running` and cannot satisfy the next
startup. Shutdown clears process handles, adoption state, and startup identity.
Persisted provider/model configuration is therefore never equivalent to a live
runtime cache.

Request cancellation is checked before managed startup begins. Once process
startup is in progress it is shared lifecycle work rather than request-owned
work, so cancelling one waiter does not tear down the runtime needed by a later
request. The lifecycle lock and failure cleanup ensure that cancellation cannot
leave a half-published `STARTING` entry.

## Configuration classification

| Configuration | llama.cpp | LiteRT-LM |
| --- | --- | --- |
| Model selection | Request-only in router mode; startup identity in single-model mode | Request-only; models load lazily |
| Model preset contents/path | Startup identity | N/A |
| Context size | Startup identity | Startup identity (`max_num_tokens`) |
| Thread count | Startup identity when supplied | Startup identity (`cpu_thread_count`) |
| Executable/runtime path or version | Supervisor/startup identity | Startup identity |
| Host/port | Supervisor identity | Startup identity |
| Backend/device | Not currently exposed as a llama startup setting | Startup identity |
| Cache policy | N/A | Startup identity |
| Temperature/top-p/top-k | Request-only unless encoded in a LiteRT server model pin | Startup identity when encoded in LiteRT `config.json` |
| Max output tokens/presence penalty | Request-only | Request-only |
| Streaming/progress/retry/UI settings | Irrelevant to runtime identity | Irrelevant to runtime identity |

The deterministic regression coverage lives in
`tests/integration/test_local_provider_lifecycle.py`. It controls only process
and health boundaries and does not require model downloads or paid services.
