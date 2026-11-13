from types import SimpleNamespace

import pytest

from tests.support import load_addon_module
from tests.support.llama_flow import gguf, llama_flow


def test_shared_primary_weights_block_owned_deletion(tmp_path, monkeypatch):
    flow = llama_flow(tmp_path, monkeypatch)
    records = load_addon_module("providers.runtime.llama_models", namespace="llama_journeys")
    path = gguf(tmp_path / "managed/cache/model.gguf")
    flow.manager._catalog.upsert(records.LlamaModelRecord("owned", str(path), "local_file", cached_path=str(path), ownership="addon"))
    flow.manager.create_configuration(str(path), "user", "Shared")
    with pytest.raises(Exception, match="Shared|user|configuration"):
        flow.manager.delete_cached_files("owned")
    assert path.is_file()


def test_legacy_projector_reference_blocks_shared_file_deletion(tmp_path, monkeypatch):
    flow = llama_flow(tmp_path, monkeypatch)
    records = load_addon_module("providers.runtime.llama_models", namespace="llama_journeys")
    path = gguf(tmp_path / "managed/cache/vision.gguf")
    flow.manager._catalog.upsert(records.LlamaModelRecord("owned", str(path), "local_file", cached_path=str(path), ownership="addon"))
    flow.manager.create_configuration("owner/model", "a", "A")
    flow.manager.set_runtime_options("a", {"mmproj": str(path)})
    with pytest.raises(Exception, match="configuration|a"):
        flow.manager.delete_cached_files("owned")
    assert path.is_file()


def test_update_name_keeps_id_selection_and_settings(tmp_path, monkeypatch):
    flow = llama_flow(tmp_path, monkeypatch)
    flow.manager.create_configuration("owner/model", "daily", "Daily", select=True)
    flow.manager.set_runtime_options("daily", {"ctx-size": "4096"})
    flow.manager.update_configuration("daily", display_name="Renamed")
    record = flow.manager.find_record("daily", register_missing=False)
    assert record.display_name == "Renamed" and record.preset_options == {"ctx-size": "4096"}
    assert flow.manager.active_model_id == "daily" and not flow.runtime.starts


def test_registry_survives_new_manager_and_close(tmp_path, monkeypatch):
    flow = llama_flow(tmp_path, monkeypatch)
    first = flow.manager.model_operations
    another = flow.module.LlamaCppModelManager(cache_dir=tmp_path / "managed", supervisor=flow.runtime,
        config=SimpleNamespace(model_name="", num_ctx=8192))
    assert another.model_operations is first
    flow.manager.close()
    assert not first._closed
    first.shutdown()


def test_edit_roundtrip_retains_explicit_hf_artifact(tmp_path, monkeypatch):
    flow = llama_flow(tmp_path, monkeypatch)
    flow.manager.create_configuration("owner/model:Q4_K_M#file=weights.gguf", "a", "A")
    entry = flow.manager.list_model_entries()[0]
    flow.manager.update_configuration("a", source=entry.source_reference, display_name="Renamed")
    record = flow.manager.find_record("a", register_missing=False)
    assert record.artifact == "weights.gguf" and record.variant == "Q4_K_M"


def test_local_companion_create_edit_export_and_shared_protection(tmp_path, monkeypatch):
    flow = llama_flow(tmp_path, monkeypatch)
    primary = gguf(tmp_path / "primary.gguf")
    vision = gguf(tmp_path / "mmproj.gguf")
    draft = gguf(tmp_path / "mtp.gguf")
    companions = [{"role": "vision", "kind": "local_file", "source": str(vision)},
        {"role": "mtp", "kind": "local_file", "source": str(draft)}]
    flow.manager.create_configuration(str(primary), "a", "A", companions=companions, select=True)
    assert not flow.runtime.starts
    record = flow.manager.find_record("a", register_missing=False)
    assert len(record.companions) == 2
    preset = (tmp_path / "managed/runtime-models.ini").read_text(encoding="utf-8")
    assert f"mmproj = {vision}" in preset and f"spec-draft-model = {draft}" in preset
    assert "spec-type = draft-mtp" in preset
    assert "image_input" in flow.manager.list_managed_models()[0].capabilities
    flow.manager.update_configuration("a", companions=[])
    assert not flow.manager.find_record("a", register_missing=False).companions
    assert "mmproj" not in (tmp_path / "managed/runtime-models.ini").read_text(encoding="utf-8")
    assert vision.is_file() and draft.is_file()


def test_hf_companion_registration_is_lazy(tmp_path, monkeypatch):
    flow = llama_flow(tmp_path, monkeypatch)
    companions = [{"role": "vision", "kind": "hugging_face", "source": "owner/model", "artifact": "mmproj.gguf"}]
    flow.manager.create_configuration("owner/model#file=weights.gguf", "a", "A", companions=companions, select=True)
    assert len(flow.manager.find_record("a", register_missing=False).companions) == 1
    assert not any(frame["type"] == "llama_resolve_companions" for frame in flow.client.commands)
    assert not flow.runtime.starts


def test_companion_load_and_unload_are_retained_application_operations(tmp_path, monkeypatch):
    from tests.support.llama_http import router_http
    flow = llama_flow(tmp_path, monkeypatch)
    primary, vision = gguf(tmp_path / "primary.gguf"), gguf(tmp_path / "mmproj.gguf")
    flow.manager.create_configuration(str(primary), "a", "A", companions=[{"role": "vision", "kind": "local_file", "source": str(vision)}])
    with router_http() as http:
        flow.executor.host, flow.executor.port = "127.0.0.1", http.port
        flow.executor.get_status = lambda: {"is_running": True, "is_adopted": False, "generation": 1, "pid": 99}
        operations = flow.manager.model_operations
        loaded = operations.start("a", "load")
        operations.wait(loaded.operation_id, timeout=4)
        assert operations.snapshots()[-1].state == "succeeded"
        assert flow.manager.find_record("a", register_missing=False).companions[0]["compatibility"] == "verified"
        flow.manager.close()
        unloaded = operations.start("a", "unload")
        operations.wait(unloaded.operation_id, timeout=4)
        assert operations.snapshots()[-1].state == "succeeded"
        assert any(method == "POST" and path == "/models/unload" for method, path, _ in http.requests)
        assert vision.is_file() and flow.manager.find_record("a", register_missing=False)
        operations.shutdown()


def test_resolved_hf_companion_reuses_verified_files_without_network(tmp_path, monkeypatch):
    import importlib
    import io
    import json
    flow = llama_flow(tmp_path, monkeypatch)
    hf = importlib.import_module("llama_journeys.worker.executors.llama_hf")
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hub"))
    body = gguf(tmp_path / "fixture.gguf").read_bytes()
    metadata = {"sha": "a" * 40, "siblings": [{"rfilename": "mmproj.gguf", "size": len(body)}]}
    monkeypatch.setattr(hf.urllib.request, "urlopen", lambda request, timeout: io.BytesIO(json.dumps(metadata).encode() if "/api/" in request.full_url else body))
    flow.manager.create_configuration("owner/model", "a", "A", companions=[{"role": "vision", "kind": "hugging_face", "source": "owner/model", "artifact": "mmproj.gguf"}])
    flow.manager.ensure_running(flow.manager.find_record("a", register_missing=False))
    def offline(*args, **kwargs):
        raise OSError("offline")
    monkeypatch.setattr(hf.urllib.request, "urlopen", offline)
    flow.manager.ensure_running(flow.manager.find_record("a", register_missing=False))
    assert len(flow.runtime.starts) == 1


def test_runtime_edits_clear_prior_companion_compatibility(tmp_path, monkeypatch):
    from dataclasses import replace
    flow = llama_flow(tmp_path, monkeypatch)
    vision = gguf(tmp_path / "mmproj.gguf")
    flow.manager.create_configuration("owner/model", "a", "A", companions=[{"role": "vision", "kind": "local_file", "source": str(vision)}])
    record = flow.manager.find_record("a", register_missing=False)
    flow.manager._catalog.upsert(replace(record, companions=tuple({**entry, "compatibility": "verified"} for entry in record.companions)))
    flow.manager.set_runtime_options("a", {"ctx-size": "4096"})
    assert flow.manager.find_record("a", register_missing=False).companions[0]["compatibility"] == "unverified"
