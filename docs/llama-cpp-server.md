# llama.cpp server integration (advanced)

This document describes the **HF-only advanced** llama.cpp preset integration.

## Scope

llama.cpp is an advanced provider. The app owns exactly one thing for it: the
model preset. It does not install `llama-server`, discover local GGUF files,
manage cache folders, delete model files, or provide onboarding.

## Model sources

Only Hugging Face sources are supported. Each of the main and optional draft
model has two source modes:

1. **Manual reference**: pass `owner/repo` or `owner/repo[:quant]` unchanged to
   llama.cpp. The add-on does not append a quant or infer a filename.
2. **Cached selection**: choose a repository from the read-only Hugging Face
   cache, then choose an exact GGUF file from its `refs/main` snapshot. The
   preset stores only the repository and repository-relative filename.

```ini
version = 1

[my-preset]
hf-repo = owner/model[:quant]
hf-file = optional/exact.gguf

spec-draft-hf = owner/draft[:quant]
spec-draft-model = optional/exact-draft.gguf
spec-type = draft-dflash
```

- `hf-repo` is required.
- `hf-file` selects an exact repository file and overrides the quant tag.
- When `hf-file` is set, `hf-repo` must not include a `:quant` suffix.
- `spec-draft-model` requires `spec-draft-hf` and a `draft-*` `spec-type`.
- Cached selection does not pin a commit. llama.cpp follows `main`; the cache
  picker displays the observed commit as advisory only.
- Local `model`, `mmproj`, `mmproj-url`, `model-url`, `docker-repo`, and
  `hf-token` keys are rejected. Tokens come from app configuration/`HF_TOKEN`.
- Projector control is `Automatic (same repository)` or `Disabled` only.
  llama.cpp has no Hugging Face projector field. Cached projectors are listed
  for information; they are not selected by the add-on.

The cache inventory reads the configured cache roots, `refs/main`, snapshot
symlinks or ordinary files, GGUF headers, and split groups. It never writes,
repairs, evicts or deletes cache entries and never stores a local path in a
preset.

## Presets

`models.json` is the authoritative list of presets. The generated
`runtime-models.ini` is written atomically from it and is never read back.
Only preset IDs are selectable in the WebView and settings model lists. Raw
`llama-server` `/models` entries are used only to enrich a matching preset's
status and capabilities; cache-only entries never become selectable IDs.
Each preset has:

- stable model ID (the request model name),
- display name,
- `hf-repo`, optional `hf-file`,
- optional draft repo/file,
- per-model runtime options,
- `spec_type_auto`, a manifest-only flag recording whether an automatically
  added speculative mode may be removed with the draft.

Supported runtime options are per-model only (`ctx-size`, `gpu-layers`,
`flash-attn`, cache/KV, MoE, projector, speculative, sampling). Server/router
settings, secrets and local paths are not preset keys.

Unknown keys, duplicate keys, invalid values, ambiguous quant+file, and source
keys outside the Hugging Face grammar are rejected with a section/key message.

## UI

The advanced preset manager provides:

- Add preset
- Edit preset
- Duplicate preset
- Remove preset
- Refresh

The editor has three tabs:

- **Model**: main source, optional draft source, projector mode.
- **Runtime**: basic per-model controls, advanced `key = value` options.
- **Preview**: generated INI with copy support.

Manual mode uses one repository reference field. Cached mode opens the cached
source picker, which lists repositories, role-filtered files, quant labels,
sizes, split state and the observed revision. The picker is shared by the main
and draft model. A draft can auto-fill a matching `draft-*` speculative mode;
`spec_type_auto` records whether the editor owns that value.

There is no remote browser, download manager, cache deletion, folder import,
local file picker, bulk import, or legacy migration.

### MoE cache and generation limits

The Runtime tab supports these settings through its basic controls and
additional `key = value` options. For example, this generated preset corresponds
to CPU MoE experts, loading mode `none`, a 3264 MiB cache, 0.95 CPU share,
99 GPU layers, Flash Attention on, 4096 context tokens and 512 output tokens:

```ini
version = 1

[my-preset]
hf-repo = owner/model
cpu-moe = true
load-mode = none
moe-cache-mib = 3264
moe-cache-cpu-share = 0.95
gpu-layers = 99
flash-attn = on
ctx-size = 4096
n-predict = 512
temperature = 0.0
```

Set context, GPU layers, Flash Attention, loading mode and expert placement
with the basic controls. Enter the cache size, CPU share, `n-predict` and
`temperature` in Additional per-model options, which also accepts `n`/`predict`
and `temp` as aliases. Basic options and their aliases (`ngl`, `fa`, `c`) belong
in the dedicated controls; entering them in Additional options reports the
correct field instead of silently discarding them. The editor exports canonical
names and takes `key = value` lines, not shell commands.

Preset temperature, top-p and output-token defaults are also used in outgoing
requests so provider-wide defaults do not overwrite them. Explicit per-model
sampling pins override those request defaults; the server's own limits still
apply. `n-predict = -1` leaves the output-token limit unspecified in requests.
Enter the prompt in chat. Model sources remain Hugging Face references; local
`-m` paths are not supported. Saving inspects the installed runtime's supported
flags before writing the preset, and runtime changes apply on the next load.

## Runtime

`llama-server` is started with `--models-preset <runtime-models.ini>`. The server
resolves and downloads `hf-repo` models through its own Hugging Face cache.
A preset with missing files still starts the router; the failure appears when the
model is loaded. Readiness must therefore be derived from the model status
(`/models`), not only from `/health`.

## Configuration

| Setting | Example | Purpose |
| --- | --- | --- |
| Server URL | `http://127.0.0.1:8081` | OpenAI-compatible endpoint |
| llama-server executable | `llama-server` | Executable name or full path |

Cache location follows llama.cpp: `LLAMA_CACHE`, `HF_HUB_CACHE`,
`HUGGINGFACE_HUB_CACHE`, `HF_HOME`, then the user Hugging Face cache.

## Diagnostics

- `/models` exposes each preset with `status.value` and `failed`/`exit_code`.
- `/models/load` is asynchronous: success only starts the load.
- Startup errors include bounded server stderr.
- Missing local paths are no longer possible; missing HF files fail on load.
