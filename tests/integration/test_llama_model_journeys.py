"""Offline integration journeys: real manager, persistence and worker commands."""
import threading

import pytest

from tests.support.llama_flow import gguf, llama_flow


@pytest.fixture
def flow(tmp_path, monkeypatch):
    return llama_flow(tmp_path, monkeypatch)


def test_cached_asset_create_use_duplicate_remove_and_reopen(flow, tmp_path):
    source = gguf(tmp_path / "hub/models--owner--model/snapshots/revision/weights.gguf")
    before = source.read_bytes()
    snapshot = flow.manager.discover_assets([{"path": str(tmp_path / "hub"), "source": "hf_hub"}])
    asset = snapshot.assets[0]
    assert (asset.repository, asset.revision, asset.artifact) == ("owner/model", "revision", "weights.gguf")
    flow.manager.create_configuration_from_asset(asset.token, "daily", "Daily", {"ctx-size": "4096"}, select=True)
    flow.saved["daily"] = flow.sampling.ModelSamplingConfig(temperature=0.4)
    flow.manager.duplicate_configuration("daily", "long", "Long context")
    flow.manager.set_runtime_options("long", {"ctx-size": "16384", "cache-type-k": "q8_0"})
    assert flow.manager.get_available_model_ids() == ["daily", "long"]
    assert flow.saved["long"].temperature == 0.4
    assert flow.manager.active_model_id == "daily"
    flow.manager.delete_model("daily")
    assert flow.manager.active_model_id is None
    assert flow.manager.get_available_model_ids() == ["long"]
    reopened = flow.module.LlamaCppModelManager(cache_dir=tmp_path / "managed", supervisor=flow.runtime)
    assert reopened.get_runtime_options("long") == {"ctx-size": "16384", "cache-type-k": "q8_0"}
    assert source.read_bytes() == before
    assert not flow.runtime.starts and flow.runtime.stops == 0


def test_hf_reference_is_lazy_and_first_use_generates_worker_preset(flow):
    flow.manager.create_configuration("owner/model:Q4_K_M#file=weights.gguf", "remote", "Remote", select=True)
    assert not flow.runtime.starts
    record = flow.manager.find_record("remote", register_missing=False)
    flow.manager.ensure_running(record)
    assert len(flow.runtime.starts) == 1
    preset = flow.runtime.starts[0][1]["models_preset"].read_text(encoding="utf-8")
    assert "hf-repo = owner/model:Q4_K_M" in preset
    assert "hf-file = weights.gguf" in preset
    assert "ctx-size = 8192" in preset
    assert flow.runtime.starts[0][1]["context"] == 0
    flow.manager.ensure_running(record)
    assert len(flow.runtime.starts) == 1
    assert any(frame["type"] == "llama_configure_preset" for frame in flow.client.commands)


def test_preset_preview_commit_is_one_time_and_retains_original(flow, tmp_path):
    source = tmp_path / "import.ini"
    original = "version = 1\n[*]\ncache-type-k = q8_0\n[a]\nhf-repo = owner/a\n[b]\nhf-repo = owner/b\n"
    source.write_text(original, encoding="utf-8")
    preview = flow.manager.preview_preset_import(str(source))
    assert not flow.manager.get_available_model_ids()
    flow.manager.commit_preset_import(preview, replace_ids=())
    assert flow.manager.get_available_model_ids() == ["a", "b"]
    assert flow.manager.get_runtime_options("b") == {"cache-type-k": "q8_0"}
    assert source.read_text(encoding="utf-8") == original
    source.write_text("version = 1\n[other]\nhf-repo = owner/other\n", encoding="utf-8")
    assert flow.manager.get_available_model_ids() == ["a", "b"]


def test_changed_discovery_asset_leaves_no_configuration_or_selection(flow, tmp_path):
    source = gguf(tmp_path / "weights.gguf")
    snapshot = flow.manager.discover_assets([{"path": str(tmp_path), "source": "user_folder"}])
    source.write_bytes(b"partial replacement")
    with pytest.raises(Exception, match="changed|missing"):
        flow.manager.create_configuration_from_asset(snapshot.assets[0].token, "a", "A", {}, select=True)
    assert not flow.manager._catalog.list_records()
    assert flow.manager.active_model_id is None
    assert not flow.runtime.starts


def test_missing_file_recovery_preserves_runtime_and_generation(flow, tmp_path):
    old = gguf(tmp_path / "old.gguf")
    flow.manager.create_configuration(str(old), "a", "A")
    flow.manager.set_runtime_options("a", {"ctx-size": "4096", "cpu-moe": "true"})
    flow.saved["a"] = flow.sampling.ModelSamplingConfig(temperature=0.3)
    old.unlink()
    assert flow.manager.get_available_model_ids() == []
    with pytest.raises(Exception, match="available"):
        flow.manager.set_active_model("a")
    replacement = gguf(tmp_path / "recovered.gguf")
    flow.manager.relocate_configuration("a", str(replacement))
    flow.manager.set_active_model("a")
    assert flow.manager.get_runtime_options("a") == {"ctx-size": "4096", "cpu-moe": "true"}
    assert flow.saved["a"].temperature == 0.3
    assert replacement.is_file() and not flow.runtime.starts


def test_stopped_prepare_never_starts_runtime_or_claims_success(flow):
    flow.manager.create_configuration("owner/model", "a", "A")
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(flow.module.RequestCancelled):
        flow.manager.prepare_configuration("a", None, cancel)
    assert not flow.runtime.starts


def test_failed_cache_root_retains_unavailable_rows(flow, tmp_path, monkeypatch):
    root = tmp_path / "cache"
    gguf(root / "weights.gguf")
    roots = [{"path": str(root), "source": "user_folder"}]
    first = flow.manager.discover_assets(roots)
    # Cache temporarily unreachable; do not replace a successful snapshot with empty.
    root.rename(tmp_path / "offline")
    failed = flow.manager.discover_assets(roots)
    assert failed.errors
    assert [asset.asset_id for asset in failed.assets] == [first.assets[0].asset_id]
    assert failed.assets[0].availability != "present"
    assert not failed.assets[0].token


@pytest.mark.parametrize("source", ["model-00001-of-00002.gguf", "mmproj-model.gguf"])
def test_direct_create_rejects_standalone_shard_or_projector(flow, tmp_path, source):
    path = gguf(tmp_path / source)
    with pytest.raises(Exception, match="single|shard|projector|standalone"):
        flow.manager.create_configuration(str(path), "a", "A")
    assert not flow.manager._catalog.list_records()


@pytest.mark.parametrize("artifact", ["model-00001-of-00002.gguf", "mmproj-model.gguf"])
def test_hf_artifact_rejects_standalone_shard_or_projector(flow, artifact):
    with pytest.raises(Exception, match="single|shard|projector|standalone"):
        flow.manager.create_configuration(f"owner/model#file={artifact}", "a", "A")
    assert not flow.manager._catalog.list_records()


def test_preset_cannot_bypass_standalone_model_policy(flow, tmp_path):
    source = tmp_path / "split.ini"
    source.write_text("version = 1\n[a]\nhf-repo = owner/model\nhf-file = model-00001-of-00002.gguf\n", encoding="utf-8")
    with pytest.raises(Exception, match="single|shard|standalone"):
        flow.manager.preview_preset_import(str(source))
    assert not flow.manager._catalog.list_records()


@pytest.mark.parametrize("source_lines", ["model = weights.gguf\nhf-repo = owner/model", "model = weights.gguf\nhf-file = ignored.gguf", "hf-repo = owner/model@dev"])
def test_ambiguous_or_unsupported_preset_source_is_rejected(flow, tmp_path, source_lines):
    source = tmp_path / "ambiguous.ini"
    source.write_text(f"version = 1\n[a]\n{source_lines}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        flow.manager.preview_preset_import(str(source))
    assert not flow.manager._catalog.list_records()


def test_owned_cache_delete_keeps_config_but_removes_selectability(flow, tmp_path):
    record_module = load_record_module()
    path = gguf(tmp_path / "managed/cache/owned.gguf")
    flow.manager._catalog.upsert(record_module.LlamaModelRecord("owned", str(path), "local_file",
        local_path=str(path), cached_path=str(path), ownership="addon"))
    assert flow.manager.get_available_model_ids() == ["owned"]
    flow.manager.delete_cached_files("owned")
    assert not path.exists()
    assert flow.manager.find_record("owned", register_missing=False)
    assert not flow.manager.get_available_model_ids()


def load_record_module():
    from tests.support import load_addon_module
    return load_addon_module("providers.runtime.llama_models", namespace="llama_journeys")


def test_user_owned_cache_delete_is_rejected_before_worker_mutation(flow, tmp_path):
    path = gguf(tmp_path / "weights.gguf")
    flow.manager.create_configuration(str(path), "a", "A")
    with pytest.raises(Exception, match="owned"):
        flow.manager.delete_cached_files("a")
    assert path.is_file()
    assert not any(frame["type"] == "llama_delete_cache" for frame in flow.client.commands)


def test_external_models_can_be_used_but_never_removed_or_prepared(flow):
    flow.runtime.models = ({"id": "external"},)
    flow.manager.set_active_model("external")
    assert flow.manager.active_model_id == "external"
    with pytest.raises(Exception, match="external"):
        flow.manager.delete_model("external")
    with pytest.raises(ValueError, match="registered"):
        flow.manager.prepare_configuration("external", None, threading.Event())
    assert not flow.manager._catalog.list_records() and not flow.runtime.starts


def test_runtime_settings_update_capabilities_and_preset_roundtrip(flow, tmp_path):
    flow.manager.create_configuration("owner/model", "a", "A")
    projector = gguf(tmp_path / "mmproj.gguf")
    options = {"mmproj": str(projector), "reasoning": "on", "cache-type-k": "q8_0", "no-kv-offload": "true", "n-cpu-moe": "4"}
    flow.manager.set_runtime_options("a", options)
    info = flow.manager.list_managed_models()[0]
    assert {"image_input", "thinking"}.issubset(info.capabilities)
    flow.manager.ensure_running(flow.manager.find_record("a", register_missing=False))
    preset = (tmp_path / "managed/runtime-models.ini").read_text(encoding="utf-8")
    assert "n-cpu-moe = 4" in preset and "no-kv-offload = true" in preset
    flow.manager.set_runtime_options("a", {})
    info = flow.manager.list_managed_models()[0]
    assert "image_input" not in info.capabilities and "thinking" not in info.capabilities
    assert "mmproj" not in (tmp_path / "managed/runtime-models.ini").read_text(encoding="utf-8")


def test_invalid_settings_leave_catalog_preset_and_selection_unchanged(flow, tmp_path):
    flow.manager.create_configuration("owner/model", "a", "A", select=True)
    manifest, preset = tmp_path / "managed/models.json", tmp_path / "managed/runtime-models.ini"
    before = manifest.read_bytes(), preset.read_bytes()
    with pytest.raises(ValueError):
        flow.manager.set_runtime_options("a", {"cache-type-k": "invented"})
    assert (manifest.read_bytes(), preset.read_bytes()) == before
    assert flow.manager.active_model_id == "a"


def test_duplicate_sampling_failure_rolls_back_new_registration(flow, monkeypatch):
    flow.manager.create_configuration("owner/model", "a", "A")
    def fail(*args):
        raise OSError("sampling disk full")
    monkeypatch.setattr(flow.sampling, "set_model_sampling", fail)
    with pytest.raises(OSError, match="disk full"):
        flow.manager.duplicate_configuration("a", "copy", "Copy")
    assert flow.manager.get_available_model_ids() == ["a"]


def test_runtime_downgrade_blocks_start_and_keeps_saved_settings(flow, monkeypatch):
    flow.manager.create_configuration("owner/model", "a", "A")
    flow.manager.set_runtime_options("a", {"moe-cache-mib": "512"})
    monkeypatch.setattr(flow.executor, "inspect_options", lambda executable: {"ctx-size"})
    with pytest.raises(Exception, match="moe-cache-mib"):
        flow.manager.ensure_running(flow.manager.find_record("a", register_missing=False))
    assert not flow.runtime.starts
    assert flow.manager.get_runtime_options("a") == {"moe-cache-mib": "512"}
    flow.manager.set_runtime_options("a", {})
    flow.manager.ensure_running(flow.manager.find_record("a", register_missing=False))
    assert len(flow.runtime.starts) == 1


@pytest.mark.parametrize("identity", ["bad\tid", "bad\x00id", "bad\x1fid"])
def test_cached_creation_rejects_control_characters_without_writing_catalog(flow, tmp_path, identity):
    gguf(tmp_path / "weights.gguf")
    asset = flow.manager.discover_assets([{"path": str(tmp_path), "source": "user_folder"}]).assets[0]
    with pytest.raises(ValueError, match="ID"):
        flow.manager.create_configuration_from_asset(asset.token, identity, "A", {})
    assert not flow.manager._catalog.list_records()


@pytest.mark.parametrize("reference,source,variant,artifact", [
    ("owner/model@main", "owner/model", None, None),
    ("hf://owner/model", "owner/model", None, None),
    ("hf://owner/model:Q4_K_M", "owner/model", "Q4_K_M", None),
    ("owner/model#file=weights.gguf", "owner/model", None, "weights.gguf"),
])
def test_preset_source_normalization_survives_preview_commit_and_export(flow, tmp_path, reference, source, variant, artifact):
    preset = tmp_path / "normalized.ini"
    preset.write_text(f"version = 1\n[a]\nhf-repo = {reference}\n", encoding="utf-8")
    flow.manager.commit_preset_import(flow.manager.preview_preset_import(str(preset)), replace_ids=())
    record = flow.manager.find_record("a", register_missing=False)
    assert (record.source, record.variant, record.artifact) == (source, variant, artifact)
    generated = (tmp_path / "managed/runtime-models.ini").read_text(encoding="utf-8")
    expected_repo = "owner/model:Q4_K_M" if variant else "owner/model"
    assert f"hf-repo = {expected_repo}\n" in generated
    if artifact:
        assert "hf-file = weights.gguf\n" in generated


def test_preset_conflicting_artifact_selectors_are_rejected(flow, tmp_path):
    preset = tmp_path / "conflict.ini"
    preset.write_text("version = 1\n[a]\nhf-repo = owner/model#file=one.gguf\nhf-file = other.gguf\n", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact|hf-file"):
        flow.manager.preview_preset_import(str(preset))
    assert not flow.manager._catalog.list_records()


@pytest.mark.parametrize("modalities", [None, 3, "image", {"image": True}])
def test_unknown_architecture_metadata_does_not_crash_or_claim_vision(flow, modalities):
    flow.manager.create_configuration("owner/model", "a", "A")
    flow.runtime.models = ({"id": "a", "status": {"value": "loaded"},
        "architecture": {"input_modalities": modalities, "output_modalities": modalities}},)
    model = flow.manager.list_managed_models()[0]
    assert "chat" in model.capabilities
    assert "image_input" not in model.capabilities


@pytest.mark.parametrize("value", [[], {}, 3])
def test_unknown_nested_status_value_is_presented_as_unknown(flow, value):
    flow.manager.create_configuration("owner/model", "a", "A")
    flow.runtime.models = ({"id": "a", "status": {"value": value}},)
    assert flow.manager.list_model_entries()[0].runtime == "unknown"
