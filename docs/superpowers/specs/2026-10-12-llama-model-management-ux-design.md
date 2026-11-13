# llama.cpp model management UX audit and design

Date: 2026-10-12. Status: proposed; source audit, not a live NVDA interaction audit.

## Intent and scope

Help users reuse downloaded models, understand what will happen when selecting a
model, and create several configurations sharing the same weights. Preserve the
recent one-time preset migration and catalog authority. This is one model-management
subsystem with staged delivery, not a redesign of chat or the native UI host.

Use “configuration” in normal UI copy. “Preset” names the INI import/export format.
A configuration is saved settings and a source reference; an asset is downloaded
files; a server entry is what an endpoint exposes. These can relate without being
identical. Selection does not imply download, loading, or successful inference.

## Current flow and findings

The entry path is AI Assistant Settings → Manage AI Providers → llama.cpp → Manage
Models. Provider Configure owns the executable/connection; Settings owns lazy,
worker-at-startup and server-at-startup policy. Model Manager owns source registration,
active selection, generation settings, runtime settings and removal.

Source references below identify actual functions in the current checkout.

| Journey | Existing behavior/evidence | Improvement |
|---|---|---|
| First setup | `ui/provider_dialog.py` separates Install, Configure and Manage Models; `ui/settings_panel.py` exposes three startup policies | Keep this split; show runtime, endpoint ownership and configuration status independently; offer Add model when no configuration exists |
| Browse configurations | `providers/llama_manager.py:list_managed_models` mixes registrations and server entries | One manager with My configurations, Downloaded models and Server models views |
| Determine readiness | Same method treats any matching server item as AVAILABLE, ignoring `status.value`; remote registrations use REGISTERED | Decode unloaded/loading/loaded/sleeping/downloading/failed/unknown; show file availability separately |
| Existing HF downloads | Remote registrations are considered REMOTE unless a stored cached_path exists; all unregistered server rows are called EXTERNAL | Discover actual downloaded assets in the worker; distinguish local cache provenance from separately managed endpoints |
| List accessibility | `ui/model_manager.py:_build_ui/_add_models` has three blank headers and symbol-only enabled/active columns; section headers are ordinary rows | Named columns, spoken text, actual row identities; no decorative selectable headers |
| Keyboard use | `_on_double_click` handles Enter/activation by toggling visibility; mouse has a checkbox-column toggle | Enter invokes the visible primary action; visibility has a labelled checkbox or dedicated command |
| Active selection | `ui/settings_panel.py:_model_choices_for` lists all managed rows, including unavailable sources, and silently falls back after errors | Share selectable-action policy across settings, gestures and model manager; retain a missing current choice as explicitly unavailable |
| Import file/HF | Separate text prompts expose Runtime model ID and repo syntax; registration uses DownloadProgressDialog despite doing no download | One Add configuration flow with friendly name, source summary, optional advanced ID and clear download-on-first-use feedback |
| Preset migration | Import is atomic for supported options and originals are unchanged; summary appears after replacement of matching IDs | Preview names, replacements and unsupported keys before commit; bind commit to the previewed bytes/digest |
| Runtime settings | `ui/llama_runtime_dialog.py` flattens controls in a scrolling dialog; only a subset of imported settings is editable; Reset clears hidden options too | Basic/Advanced sections, effective values and origins, an explicit all-options reset summary; unsupported saved values remain visible and individually resettable |
| Context control | Context exists in generation settings and runtime settings, while provider defaults are applied during export | Explain server allocation versus request/context budget and show their effective relationship; remove ambiguous duplicate labels |
| Settings lookup | `_on_runtime_settings` uses `_run_mutation`, whose finalizer invalidates catalogs, refreshes and sets list focus | Separate read tasks from mutations; reading settings never rebuilds rows or takes focus |
| Refresh/error | Generation fences and last catalog retention exist; `_on_models_fetch_error` repopulates without the saved selection; no stale-age indication | Preserve view, filter, selection, scroll and actual keyboard focus; show stale data and per-source failures |
| Remove/close | Removal stops an owned router and preserves shared files; exact IDs/tombstones already exist; closing cancels pending task delivery | Keep ownership checks; name action Remove configuration; make shared-weight relationships explicit; late callbacks never reopen closed dialogs |

## Proposed user experience

One dialog with a labelled View choice (default My configurations), Search, model
list, read-only details, contextual primary/secondary actions, Refresh and Close.
Remember the view/filter during that dialog session. Empty My configurations offers
Add configuration and Browse downloaded models. Unknown cache locations offer
Choose cache folder; a discovery error is not an empty-cache result.

My configurations columns: Name, Selected, Files, Runtime. Downloaded models:
Model/file name, Cache source, Size, Configurations using this model. Server models:
Server model ID, Runtime, Management. Details include stable configuration ID,
repository/revision/artifact when verified, path, quantization/capability confidence,
source ownership, related configurations, effective settings and last failure.
Unknown metadata is labelled Unknown, never inferred from a friendly filename.

A single local asset can back Everyday and Long context configurations. Each has its
own stable ID, friendly display name and settings. Removing either keeps the files
and the other configuration. Raw cache entries stay in the downloaded-assets view;
registered configurations are the ordinary active-model choices. Separately managed
server entries remain selectable when their endpoint is available, without becoming
registrations automatically.

Primary actions: Use for selectable configurations/server entries; Create
configuration for verified compatible assets; Locate files for missing local sources.
Use saves selection without loading. An explicit Prepare model action may start the
owned server/load the configuration, with cancellation and stage feedback. Existing
lazy inference remains the default. Do not advertise standalone Download now until
its worker/native lifecycle and terminal semantics are implemented and tested.

Create configuration from cache: select asset → verified source/size summary → friendly
name (advanced stable ID optional) → optional settings → Create or Create and use.
No copies, downloads, server startup or inferred deletion ownership. Revalidate the
asset token/file identity at commit. A race with cache cleanup leaves no broken new
registration. Conflicting IDs require a new ID or explicit Replace; never overwrite
silently. Duplicate asset bytes may have multiple intentional configurations.

Local llama.cpp download cache, HF Hub cache and user-selected folders have different
provenance. Respect worker-visible LLAMA_CACHE, explicit saved roots, and verified
HF Hub snapshot metadata. Do not assume both caches share a location. If a platform
cache root cannot be reliably discovered from the installed runtime/configuration,
ask for a folder rather than inventing one. Browse is local-only, works with the
server stopped, and never starts an inference server. Symlinks, HF blob links,
missing files and incomplete downloads need explicit status and revalidation.
Existing supported projector associations may be retained; do not broaden model
import to unsupported shard/multi-file layouts as part of this work.

Refresh preserves the focused control. Only an explicit completed action may move
selection to its resulting row; passive completion does not steal keyboard focus.
Announce “Scanning downloaded models”, one delayed-progress message when needed,
and one concise terminal summary. Distinguish stopped/cancelled from failed; show
specific recovery actions without repeated readiness speech. Speech, focus and NVDA
object access stay in the NVDA process.

## Architecture and invariants

- `models.json` remains authoritative; generated presets and external INI files are
  never rediscovered as authoritative state.
- Worker discovery produces immutable asset snapshots and opaque verification tokens.
  Python merges snapshots with catalog registrations and server observations.
- A single presenter/policy computes entries, labels, primary actions and eligibility
  for Model Manager, settings dropdown and gestures. UI does not reconstruct policy.
- Discovery has cancellation, deadlines, generations and per-root errors. Health,
  Stop and shutdown remain responsive while scanning.
- UI read tasks and mutations have separate completion policies. Mutation invalidation
  happens after durable commit; late/stale results cannot undo a newer action.
- Managed server lifecycle remains native-supervisor owned. Do not introduce CLI
  launches in NVDA, provider calls in UI, or business logic in Rust/Svelte.
- All user-facing strings use literal gettext templates. Keep generic-provider
  behavior unchanged except separately tested shared accessibility corrections.
- Shared cache deletion is outside this delivery. Existing verified add-on-owned
  deletion remains a separate, explicit action; no new ownership is inferred.

## Acceptance journeys

1. A first-time user can add an HF reference and hear that files may download on first use.
2. An offline user finds a verified downloaded GGUF and creates/uses a configuration
   without network activity or inference-server startup.
3. Two named configurations share one asset; deleting one affects neither weights nor
   the other configuration.
4. Loaded, unloaded, downloading, failed and unknown server states have distinct copy.
5. A missing source stays editable/removable but is absent from ordinary selectable choices.
6. Refresh failure retains rows, selection and focused search field, with stale status.
7. Stop/close during discovery or preparation responds promptly and discards late UI results.
8. Unsupported INI options and colliding IDs are visible before import; cancellation
   and preview drift leave catalog and active choice unchanged.
9. Keyboard-only NVDA users can identify every column, choose the primary action,
   edit/reset settings and dismiss every dialog with Escape.
10. Browsing another provider and its existing imports/actions still works.

## Evidence and scope limits

The audit is based on the current Python UI, model manager, adapter, task runner,
settings and worker code. It does not certify live screen-reader announcements or
native focus behavior; those require the manual acceptance pass in the plan.

Upstream documents separate cache, model-directory and preset sources, runtime
statuses, model loading, and duplicate-cache handling:
https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md#using-multiple-models
Pin compatibility fixtures to the installed binary; upstream master is not a version
floor. HF Hub cache metadata/layout must also be tested against supported fixtures.
