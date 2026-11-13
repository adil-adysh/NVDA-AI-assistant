from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.support import load_addon_module

NAMESPACE = "deterministic_llama_tests"
models = load_addon_module("providers.runtime.llama_models", namespace=NAMESPACE)
contracts = load_addon_module("providers.model_manager", namespace=NAMESPACE)
manager_module = load_addon_module("providers.llama_manager", namespace=NAMESPACE)
preset = load_addon_module("core.llama_preset", namespace=NAMESPACE)


def record(model_id="local", source="local.gguf"):
    return models.LlamaModelRecord(model_id, source, "local_file", local_path=source)


def test_codec_generation_is_order_independent():
    codec = preset.LlamaPresetCodec()
    assert codec.encode([record("z"), record("a")]) == codec.encode([record("a"), record("z")])


def test_codec_rejects_unknown_version_and_preserves_unknown_options():
    codec = preset.LlamaPresetCodec()
    with pytest.raises(ValueError, match="version"):
        codec.validate("version = 2\n[local]\nmodel = local.gguf\n")
    text = "version = 1\n# comment\n[local]\nmodel = local.gguf\nfuture-option = keep\n"
    assert "future-option = keep" in codec.reconcile(text, [record()])


def test_removal_does_not_rewrite_user_preset(tmp_path):
    source = tmp_path / "user.ini"
    original = "version = 1\n[local]\nmodel = missing.gguf\ncache-type-k = q8_0\n"
    source.write_text(original, encoding="utf-8")
    catalog = models.LlamaModelCatalog(tmp_path / "managed", preset_path=source)
    effective = catalog.write_preset()
    assert effective != source
    catalog.remove("local")
    assert source.read_text(encoding="utf-8") == original
    assert not catalog.list_records()
    assert "[local]" not in catalog.write_preset().read_text(encoding="utf-8")
    catalog.remove("local")
    assert not catalog.list_records()


def test_missing_import_remains_removable_and_external_row_is_read_only(tmp_path):
    supervisor = Mock()
    supervisor.list_models.return_value = ({"id": "external"},)
    manager = manager_module.LlamaCppModelManager(cache_dir=tmp_path, supervisor=supervisor)
    manager._catalog.upsert(record(source=str(tmp_path / "missing.gguf")))
    rows = {item.id: item for item in manager.list_managed_models()}
    assert contracts.ModelAction.REMOVE in rows["local"].actions
    assert contracts.ModelAction.REMOVE not in rows["external"].actions
    assert rows["external"].ownership is contracts.ModelOwnership.EXTERNAL


def test_remove_clears_active_selection_and_fences_server_echo(tmp_path):
    supervisor = Mock()
    supervisor.is_running = True
    supervisor.is_adopted = False
    supervisor.status.return_value = SimpleNamespace(is_running=True, is_adopted=False)
    supervisor.list_models.return_value = ({"id": "local"},)
    saved = []
    config = SimpleNamespace(model_name="local")
    manager = manager_module.LlamaCppModelManager(config=config, cache_dir=tmp_path,
        supervisor=supervisor, set_model_fn=saved.append)
    manager._catalog.upsert(record(source=str(tmp_path / "missing.gguf")))
    manager.delete_model("local")
    supervisor.stop.assert_called_once()
    assert saved == [""]
    assert manager.active_model_id is None
    assert not manager.list_managed_models()
    manager.delete_model("local")
    supervisor.stop.assert_called_once()


def test_delete_external_identity_never_auto_imports(tmp_path):
    supervisor = Mock()
    manager = manager_module.LlamaCppModelManager(cache_dir=tmp_path, supervisor=supervisor)
    with pytest.raises(manager_module.LLMProviderError):
        manager.delete_model("owner/external-model")
    assert not manager._catalog.list_records()


def test_failed_preset_write_rolls_back_registration(tmp_path, monkeypatch):
    catalog = models.LlamaModelCatalog(tmp_path)
    catalog.upsert(record("old"))
    monkeypatch.setattr(catalog, "_atomic_preset", Mock(side_effect=OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        catalog.upsert(record("new"))
    assert {item.model_id for item in catalog.list_records()} == {"old"}


def test_user_file_never_offers_cache_deletion(tmp_path):
    source = tmp_path / "user.gguf"
    source.write_bytes(b"model")
    supervisor = Mock()
    supervisor.list_models.return_value = ()
    manager = manager_module.LlamaCppModelManager(cache_dir=tmp_path / "managed", supervisor=supervisor)
    manager._catalog.upsert(record(source=str(source)))
    row = manager.list_managed_models()[0]
    assert contracts.ModelAction.DELETE_CACHE not in row.actions
    with pytest.raises(manager_module.LLMProviderError, match="owned"):
        manager.delete_cached_files("local")
    assert source.exists()


def test_stop_failure_preserves_registration(tmp_path):
    supervisor = Mock()
    supervisor.is_running = True
    supervisor.is_adopted = False
    supervisor.status.return_value = SimpleNamespace(is_running=True, is_adopted=False)
    supervisor.stop.side_effect = RuntimeError("worker crashed")
    manager = manager_module.LlamaCppModelManager(cache_dir=tmp_path, supervisor=supervisor)
    manager._catalog.upsert(record())
    with pytest.raises(RuntimeError, match="worker crashed"):
        manager.delete_model("local")
    assert manager._catalog.find_exact("local") is not None


def test_import_preset_preserves_original_and_validates_before_settings(tmp_path):
    source = tmp_path / "user.ini"
    original = "version = 1\n[remote]\nhf-repo = owner/model\ncache-type-k = q8_0\n"
    source.write_text(original, encoding="utf-8")
    saved = []
    manager = manager_module.LlamaCppModelManager(cache_dir=tmp_path / "managed", supervisor=Mock(), set_preset_fn=saved.append)
    manager.import_preset(source)
    assert saved == []
    assert source.read_text(encoding="utf-8") == original
    assert "cache-type-k = q8_0" in manager._catalog.write_preset().read_text(encoding="utf-8")
    source.write_text("version = 99\n", encoding="utf-8")
    with pytest.raises(ValueError, match="version"):
        manager.import_preset(source)
    assert saved == []


def test_catalog_instances_share_serialization_and_legacy_manifest_migrates(tmp_path):
    import json
    legacy = [{"model_id": "old", "source": "owner/model", "kind": "hugging_face"}]
    (tmp_path / "models.json").write_text(json.dumps(legacy), encoding="utf-8")
    first, second = models.LlamaModelCatalog(tmp_path), models.LlamaModelCatalog(tmp_path)
    assert first.lock is second.lock
    first.upsert(record("new"))
    assert {item.model_id for item in second.list_records()} == {"old", "new"}
    assert json.loads((tmp_path / "models.json").read_text(encoding="utf-8"))["version"] == 1


def test_explicit_reimport_restores_retired_registration(tmp_path):
    catalog = models.LlamaModelCatalog(tmp_path)
    model = record()
    catalog.upsert(model)
    catalog.remove("local")
    assert catalog.find("local.gguf") is None
    catalog.upsert(model)
    assert catalog.find_exact("local") is not None


def test_cancelled_worker_cache_delete_preserves_owned_file(tmp_path):
    execution = load_addon_module("core.job.execution", namespace=NAMESPACE)
    cancellation = load_addon_module("core.job.cancellation", namespace=NAMESPACE)
    worker = load_addon_module("worker.executors.llama", namespace=NAMESPACE)
    root = tmp_path / "cache"
    root.mkdir()
    target = root / "owned.gguf"
    target.write_bytes(b"model")
    import json
    (root.parent / "models.json").write_text(json.dumps({"version": 1, "models": [{"model_id": "owned", "ownership": "addon", "cached_path": str(target)}]}), encoding="utf-8")
    token = cancellation.CancellationToken("cache-delete")
    token.cancel()
    with execution.job_execution_scope(token):
        with pytest.raises(cancellation.JobCancelledError):
            worker.LlamaWorkerExecutor(owned_cache_root=root).delete_cache(str(root), str(target), model_id="owned")
    assert target.exists()


def test_worker_cache_delete_is_contained_and_idempotent(tmp_path):
    worker = load_addon_module("worker.executors.llama", namespace=NAMESPACE)
    root = tmp_path / "cache"
    root.mkdir()
    outside = tmp_path / "user.gguf"
    outside.write_bytes(b"user model")
    executor = worker.LlamaWorkerExecutor(owned_cache_root=root)
    with pytest.raises(ValueError, match="outside"):
        executor.delete_cache(str(root), str(outside))
    assert outside.exists()
    owned = root / "owned.gguf"
    owned.write_bytes(b"owned")
    import json
    (root.parent / "models.json").write_text(json.dumps({"version": 1, "models": [{"model_id": "owned", "ownership": "addon", "cached_path": str(owned)}]}), encoding="utf-8")
    assert executor.delete_cache(str(root), str(owned), model_id="owned")["success"]
    assert executor.delete_cache(str(root), str(owned), model_id="owned")["success"]
    assert not owned.exists()


def test_provider_catalog_does_not_register_external_huggingface_identity(tmp_path):
    adapter = load_addon_module("providers.adapters.llama_cpp", namespace=NAMESPACE)
    provider = object.__new__(adapter.LlamaCppServerProvider)
    provider._config = SimpleNamespace(provider="llama-cpp-server", model_name="owner/external")
    provider._provider_id = "llama-cpp-server"
    supervisor = Mock()
    supervisor.list_models.return_value = ({"id": "owner/external"},)
    provider._llama_manager = manager_module.LlamaCppModelManager(cache_dir=tmp_path, supervisor=supervisor)
    assert provider.list_models()[0].id == "owner/external"
    assert not provider._llama_manager._catalog.list_records()


def test_unrelated_removal_does_not_reimport_user_preset_edits(tmp_path):
    source = tmp_path / "user.ini"
    source.write_text("version = 1\n[a]\nhf-repo = owner/old\n[b]\nhf-repo = owner/remove\n", encoding="utf-8")
    catalog = models.LlamaModelCatalog(tmp_path / "managed", preset_path=source)
    catalog.remove("b")
    source.write_text("version = 1\n[a]\nhf-repo = owner/new\nhf-file = changed.gguf\nctx-size = 4096\n", encoding="utf-8")
    current = catalog.list_records()
    assert len(current) == 1
    assert current[0].source == "owner/old"
    assert current[0].artifact is None
    assert current[0].context_window is None
    assert "owner/old" in catalog.write_preset().read_text(encoding="utf-8")


def test_worker_does_not_trust_caller_supplied_cache_root(tmp_path):
    worker = load_addon_module("worker.executors.llama", namespace=NAMESPACE)
    user_cache = tmp_path / "user/cache"
    user_cache.mkdir(parents=True)
    target = user_cache / "user.gguf"
    target.write_bytes(b"user")
    with pytest.raises(ValueError):
        worker.LlamaWorkerExecutor().delete_cache(str(user_cache), str(target))
    assert target.exists()


def test_worker_status_failure_does_not_remove_registration(tmp_path):
    runtime = load_addon_module("providers.runtime.llama_server", namespace=NAMESPACE)
    client = Mock()
    client.is_connected = True
    client.send_command.side_effect = RuntimeError("worker unresponsive")
    supervisor = runtime.LlamaServerSupervisor(worker_client=client)
    manager = manager_module.LlamaCppModelManager(cache_dir=tmp_path, supervisor=supervisor)
    manager._catalog.upsert(record())
    with pytest.raises(runtime.LlamaServerError):
        manager.delete_model("local")
    assert manager._catalog.find_exact("local") is not None


def test_removal_preserves_selection_changed_after_compare_and_set(tmp_path):
    config = SimpleNamespace(model_name="local")
    supervisor = Mock()
    supervisor.status.return_value = SimpleNamespace(is_running=False, is_adopted=False)
    def clear_then_select_new(expected, value):
        assert expected == "local" and value == ""
        config.model_name = "new"
        return True
    manager = manager_module.LlamaCppModelManager(config=config, cache_dir=tmp_path,
        supervisor=supervisor, clear_model_fn=clear_then_select_new)
    manager._catalog.upsert(record())
    manager.delete_model("local")
    assert manager.active_model_id == "new"


def test_removal_does_not_clear_a_different_exact_id_with_same_casefold(tmp_path):
    config = SimpleNamespace(model_name="model")
    supervisor = Mock()
    supervisor.status.return_value = SimpleNamespace(is_running=False, is_adopted=False)
    supervisor.list_models.return_value = ({"id": "model"},)
    saved = []
    manager = manager_module.LlamaCppModelManager(config=config, cache_dir=tmp_path,
        supervisor=supervisor, set_model_fn=saved.append)
    manager._catalog.upsert(record("Model", "upper.gguf"))
    manager._catalog.upsert(record("model", "lower.gguf"))
    assert manager._catalog.find("model").model_id == "model"
    manager.delete_model("Model")
    assert not saved
    assert manager.active_model_id == "model"
    assert manager.list_server_models(refresh=True) == ({"id": "model"},)
