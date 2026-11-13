from pathlib import Path

from tests.support import load_addon_module


def modules():
    return (load_addon_module("providers.llama_catalog", namespace="llama_ux"),
            load_addon_module("providers.runtime.llama_models", namespace="llama_ux"))


def test_unloaded_and_missing_sources_are_distinct(tmp_path):
    catalog, records = modules()
    local = records.LlamaModelRecord("missing", str(tmp_path / "gone.gguf"), "local_file")
    remote = records.LlamaModelRecord("remote", "owner/model", "hugging_face")
    entries = catalog.reconcile_llama_entries([local, remote], [], [{"id": "remote", "status": {"value": "unloaded"}}], endpoint_owned=True)
    rows = {entry.model.id: entry for entry in entries}
    assert rows["remote"].runtime == "unloaded"
    assert "missing" not in {entry.model.id for entry in catalog.selectable_llama_entries(entries)}
    assert rows["missing"].model.registered


def test_external_paths_are_not_downloaded_assets(tmp_path):
    catalog, _ = modules()
    local = tmp_path / "model.gguf"
    local.write_bytes(b"GGUF")
    entries = catalog.reconcile_llama_entries([], [], [{"id": "external", "path": str(local), "status": {"value": "loaded"}}], endpoint_owned=False)
    assert entries[0].kind == "server"
    assert entries[0].asset_id is None


def test_two_configurations_share_an_asset_without_merging_ids(tmp_path):
    catalog, records = modules()
    assets = load_addon_module("core.model_assets", namespace="llama_ux")
    path = str(Path(tmp_path / "model.gguf"))
    Path(path).write_bytes(b"GGUF")
    asset = assets.ModelAssetSnapshot("asset", "token", path, "hf_hub", "present", 4, file_identity="identity")
    configurations = [records.LlamaModelRecord(name, path, "local_file", display_name=name, asset_id="asset") for name in ("everyday", "long-context")]
    entries = catalog.reconcile_llama_entries(configurations, [asset], [], endpoint_owned=True)
    downloaded = next(entry for entry in entries if entry.kind == "downloaded")
    assert downloaded.configuration_ids == ("everyday", "long-context")
    assert {entry.model.id for entry in catalog.selectable_llama_entries(entries)} == {"everyday", "long-context"}


def test_declared_projector_capability_is_not_lost_before_loading():
    catalog, records = modules()
    record = records.LlamaModelRecord("vision", "owner/model", "hugging_face", capabilities=("chat", "image_input"))
    items = [{"id": "vision", "status": {"value": "unloaded"}, "architecture": {"input_modalities": ["text"]}}]
    row = catalog.reconcile_llama_entries([record], [], items, endpoint_owned=True)[0]
    assert "image_input" in row.model.capabilities
    items[0]["status"]["value"] = "loaded"
    row = catalog.reconcile_llama_entries([record], [], items, endpoint_owned=True)[0]
    assert "image_input" not in row.model.capabilities


def test_stale_asset_cannot_make_deleted_configuration_selectable(tmp_path):
    catalog, records = modules()
    assets = load_addon_module("core.model_assets", namespace="llama_ux")
    path = str(tmp_path / "deleted.gguf")
    asset = assets.ModelAssetSnapshot("asset", "token", path, "hf_hub", "present", 24)
    record = records.LlamaModelRecord("missing", path, "local_file", asset_id="asset")
    rows = catalog.reconcile_llama_entries([record], [asset], [], endpoint_owned=True)
    assert catalog.selectable_llama_entries(rows) == []
    assert catalog.ModelAction.LOCATE_SOURCE in rows[0].model.actions


def test_stale_external_models_remain_visible_but_not_selectable():
    catalog, _ = modules()
    rows = catalog.reconcile_llama_entries([], [], [{"id": "external"}], endpoint_owned=False, stale=True)
    assert rows[0].stale
    assert catalog.selectable_llama_entries(rows) == []
