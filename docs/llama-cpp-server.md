# llama.cpp server integration

This document describes the NVDA AI Assistant integration with `llama-server` from llama.cpp.

## Architecture

The integration has four boundaries:

1. The provider configuration stores the endpoint, executable, selected model, and optional preset path.
2. `LlamaModelCatalog` owns imported model identities and preset reconciliation.
3. `LlamaServerSupervisor` owns the process and the cached server model API response.
4. `LlamaCppServerProvider` translates server metadata into provider-neutral model information and sends the canonical model ID to the OpenAI-compatible client.

The server API is authoritative for runtime state. The local manifest is not a second runtime model catalog; it only preserves import metadata and generates the preset.

## Configuration

Configure llama.cpp under **Manage AI Providers**:

| Setting | Example | Purpose |
| --- | --- | --- |
| Server URL | `http://127.0.0.1:8081` | OpenAI-compatible llama-server endpoint |
| llama-server executable | `llama-server` | Executable name or full path; `PATH` is used when blank |
| Models preset path | `D:\llama-cpp\models.ini` | Optional user-owned router preset |

When no preset path is configured, the addon uses:

```text
%APPDATA%\nvda\AIAssistant\models\llama-cpp\models.ini
```

The import manifest is stored beside the default preset as `models.json`. When a custom preset is configured, the manifest remains application-owned while the specified preset is used as the reconciliation target.

## Presets

llama-server presets contain model-router configuration, not server endpoint configuration. Host and port belong in the addon/server configuration, not in `models.ini`.

Supported model entries include:

```ini
version = 1

[*]
ctx-size = 36864
flash-attn = true

[local-model]
model = C:\models\model.gguf

[remote-model]
hf-repo = org/model:Q4_K_M
```

The addon preserves the preset’s global section, comments, and model-specific options. It updates only model source entries when imported records are reconciled.

## Lifecycle

When llama.cpp becomes active, or before a chat/use case starts, the addon:

1. resolves the configured executable, using `PATH` when no explicit executable is set;
2. loads the selected model identity from the local catalog or preset;
3. starts `llama-server --models-preset <path> --host <host> --port <port>` when needed;
4. waits for the endpoint to become healthy;
5. queries `/models`, falling back to `/v1/models`;
6. validates that the selected model is exposed by the server;
7. sends the canonical preset section ID in the OpenAI-compatible request.

If a healthy server already exists after NVDA restarts, the addon can adopt it when the requested model is present. It refuses to silently take ownership of a server exposing a different model catalog.

## Model switching

llama-server router mode supports multiple models. A healthy router is kept alive while the selected model changes. The addon validates the target against the cached server model catalog and sends that model ID in the request. It does not restart the server for a normal model switch.

A restart is reserved for:

* an unhealthy or exited process;
* a changed endpoint or executable configuration;
* an explicitly recreated runtime process.

## API model catalog and capabilities

Successful model API responses are cached in the application-owned supervisor and invalidated when the server starts, is adopted, or stops. The cached response is used for:

* model availability and identity matching;
* router adoption;
* model switching validation;
* provider model lists;
* capability discovery.

The addon maps llama metadata as follows:

| llama metadata | Provider capability/field |
| --- | --- |
| `architecture.input_modalities: text` | `text_input` |
| `architecture.input_modalities: image` | `image_input` |
| `architecture.input_modalities: audio` | `audio_input` |
| `architecture.output_modalities: text` | `text_output` |
| `architecture.output_modalities: image` | `image_output` |
| `meta.n_ctx_train` | `context_window` |
| `status` and complete raw object | retained in `ProviderModelInfo.raw` |

Streaming and chat/completion are advertised because they are provided by the OpenAI-compatible llama-server adapter. Tool support is not inferred from model names or generic server support.

## Identity matching

These forms can identify the same imported Hugging Face model:

```text
gemma4-26b
WhiskyAKM/Gemma-4-26B-A4B-NVFP4-GGUF:NVFP4
hf://WhiskyAKM/Gemma-4-26B-A4B-NVFP4-GGUF:NVFP4
```

The preset section ID is used as the canonical request model ID because it is stable and independent of local cache paths.

## Diagnostics

Inspect the server catalog directly:

```powershell
Invoke-RestMethod http://127.0.0.1:8081/models
```

If that endpoint is unavailable, test the OpenAI-compatible fallback:

```powershell
Invoke-RestMethod http://127.0.0.1:8081/v1/models
```

Check that the response contains the selected preset ID or an equivalent recognized source alias. If the response does not contain the model, the addon reports that the model is not exposed by the server instead of treating the local manifest as proof of runtime availability.

## Source references

The integration follows llama.cpp’s documented router and model metadata endpoints:

* [Model presets](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md#model-presets)
* [OpenAI-compatible `/v1/models`](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md#get-v1models-openai-compatible-model-info-api)
* [`/models` model catalog and architecture metadata](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md#get-models-list-available-models)
