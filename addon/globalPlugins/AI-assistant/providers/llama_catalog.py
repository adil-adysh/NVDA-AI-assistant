"""One presentation policy for configured, downloaded and server model entries."""
from dataclasses import dataclass
from pathlib import Path

from ..core.translation import _
from ..core.model_assets import ModelAssetSnapshot
from .model_manager import ManagedModel, ModelState, ModelAction, ModelOwnership, ModelFileAvailability, ModelRuntimeState
from .runtime.llama_models import llama_model_capabilities


@dataclass(frozen=True)
class LlamaModelEntry:
	model: ManagedModel
	kind: str
	asset_id: str | None = None
	configuration_ids: tuple[str, ...] = ()
	runtime: str = "unknown"
	stale: bool = False
	asset: object | None = None
	source_reference: str = ""
	runtime_options: tuple[tuple[str, str], ...] = ()
	companions: tuple[dict, ...] = ()


def runtime_state(item):
	if not item:
		return "stopped"
	status = item.get("status") or {}
	if not isinstance(status, dict):
		return "unknown"
	if status.get("failed"):
		return "failed"
	value = status.get("value", "unknown")
	return value if isinstance(value, str) and value in {"loaded", "unloaded", "loading", "downloading", "sleeping", "failed"} else "unknown"


def configuration_capabilities(item, declared):
	if not item:
		return tuple(declared)
	observed = set(llama_model_capabilities(item))
	if runtime_state(item) != "loaded":
		observed.update(declared)
	return tuple(sorted(observed))


def reconcile_llama_entries(records, assets, server_items, *, endpoint_owned: bool, stale: bool = False):
	entries = []
	matched = set()
	for record in records:
		item = next((item for item in server_items if str(item.get("id", "")) == record.model_id), None)
		if item is None:
			item = next((item for item in server_items if record.matches_server_id(str(item.get("id", "")))
				and str(item.get("id", "")) not in {other.model_id for other in records}), None)
		if item:
			matched.add(str(item.get("id", "")))
		asset = next((asset for asset in assets if record.asset_id and asset.asset_id == record.asset_id), None)
		remote = record.kind == "hugging_face"
		path = record.cached_path or record.local_path or (record.source if not remote else None)
		present = bool(path and Path(path).is_file()) if path else bool(asset and Path(asset.path).is_file())
		if asset is None and record.asset_id and path:
			asset = ModelAssetSnapshot(record.asset_id, "", path, record.asset_source or "user_folder",
				"present" if present else "missing", None, repository=record.asset_repository,
				revision=record.asset_revision, artifact=record.asset_artifact)
		files = ModelFileAvailability.PRESENT if present else ModelFileAvailability.REMOTE if remote else ModelFileAvailability.MISSING
		state = ModelState.DOWNLOADED if present else ModelState.REGISTERED if remote else ModelState.NOT_DOWNLOADED
		runtime = "unknown" if stale else runtime_state(item)
		actions = [ModelAction.REMOVE, ModelAction.EDIT_RUNTIME, ModelAction.EDIT_GENERATION]
		if present or remote:
			actions.append(ModelAction.SELECT)
		if not remote and not present:
			actions.append(ModelAction.LOCATE_SOURCE)
		companions = getattr(record, "companions", ())
		declared = set(record.capabilities)
		if any(companion["role"] == "vision" for companion in companions):
			declared.add("image_input")
		caps = configuration_capabilities(item, declared)
		model = ManagedModel(record.model_id, record.display_name or record.model_id, state, capabilities=caps,
			registered=True, ownership=ModelOwnership(record.ownership), file_availability=files,
			runtime_state=ModelRuntimeState(runtime), actions=tuple(actions),
			description=_("Files may download on first use.") if remote and not present else _("Removing this configuration preserves the model files."))
		related = tuple(sorted(other.model_id for other in records if other.asset_id and other.asset_id == record.asset_id))
		source_reference = record.server_model
		if remote and record.artifact:
			source_reference += "#file=" + record.artifact
		entries.append(LlamaModelEntry(model, "configuration", record.asset_id, related, runtime=runtime, stale=stale, asset=asset,
			source_reference=source_reference, runtime_options=tuple(sorted(record.preset_options.items())), companions=companions))
	for asset in assets:
		related = tuple(sorted(record.model_id for record in records if record.asset_id == asset.asset_id
			or (record.local_path and Path(record.local_path).resolve() == Path(asset.path).resolve())))
		actions = (ModelAction.CREATE_CONFIGURATION,) if asset.availability == "present" else ()
		model = ManagedModel(asset.asset_id, Path(asset.path).name, ModelState.DOWNLOADED if actions else ModelState.NOT_DOWNLOADED,
			size_hint=_("{size} MiB").format(size=round((asset.size_bytes or 0) / 1048576, 1)),
			file_availability=ModelFileAvailability.PRESENT if actions else ModelFileAvailability.UNKNOWN,
			capabilities=asset.capabilities, actions=actions, description=asset.path)
		entries.append(LlamaModelEntry(model, "downloaded", asset.asset_id, related, asset=asset, stale=stale))
	for item in server_items:
		identity = str(item.get("id", ""))
		if not identity or identity in matched:
			continue
		runtime = "unknown" if stale else runtime_state(item)
		model = ManagedModel(identity, identity, ModelState.READY, capabilities=llama_model_capabilities(item),
			runtime_state=ModelRuntimeState.UNKNOWN if stale else ModelRuntimeState(runtime), actions=() if stale else (ModelAction.SELECT,),
			description=_("Exposed by the managed server; create a configuration from a verified local asset to customize it.")
			if endpoint_owned else _("Managed by a separate server. Its files and settings cannot be changed here."))
		entries.append(LlamaModelEntry(model, "server", runtime=runtime, stale=stale))
	return sorted(entries, key=lambda entry: (entry.kind, entry.model.display_name.casefold(), entry.model.id))


def selectable_llama_entries(entries):
	return [entry for entry in entries if ModelAction.SELECT in (entry.model.actions or ())]


def runtime_label(value):
	return {"loaded": _("Loaded"), "unloaded": _("Not loaded"), "loading": _("Loading"),
		"downloading": _("Downloading"), "sleeping": _("Sleeping"), "failed": _("Failed"),
		"stopped": _("Server stopped"), "unknown": _("Unknown")}.get(value, _("Unknown"))


def files_label(value):
	return {ModelFileAvailability.PRESENT: _("Downloaded"), ModelFileAvailability.REMOTE: _("May download on first use"),
		ModelFileAvailability.MISSING: _("Files missing"), ModelFileAvailability.UNKNOWN: _("Unknown")}[value]


def cache_source_label(source):
	return {"llama_cache": _("llama.cpp cache"), "hf_hub": _("Hugging Face Hub cache"),
		"user_folder": _("Chosen folder")}.get(source, _("Unknown"))
