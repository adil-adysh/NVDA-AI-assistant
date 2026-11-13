from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.support import load_addon_module

models = load_addon_module("providers.runtime.llama_models", namespace="preset_migration")
manager_module = load_addon_module("providers.llama_manager", namespace="preset_migration")


def test_import_is_snapshot_and_survives_source_deletion(tmp_path):
    source = tmp_path / "user.ini"
    source.write_text("version = 1\n[*]\ncache-type-k = q8_0\n[a]\nmodel = local.gguf\nn-cpu-moe = 8\n", encoding="utf-8")
    catalog = models.LlamaModelCatalog(tmp_path / "managed", preset_path=source)
    first = catalog.write_preset().read_text(encoding="utf-8")
    source.unlink()
    second = models.LlamaModelCatalog(tmp_path / "managed", preset_path=source)
    assert second.write_preset().read_text(encoding="utf-8") == first
    assert second.list_records()[0].preset_options == {"cache-type-k": "q8_0", "n-cpu-moe": "8"}


def test_unsupported_import_is_atomic_and_reports_options(tmp_path):
    source = tmp_path / "user.ini"
    source.write_text("version = 1\n[a]\nhf-repo = owner/model\nunknown-option = value\n", encoding="utf-8")
    catalog = models.LlamaModelCatalog(tmp_path / "managed")
    with pytest.raises(ValueError, match="unknown-option"):
        catalog.import_preset(source)
    assert not catalog.list_records()
    assert not (tmp_path / "managed/models.json").exists()


def test_explicit_import_merges_and_no_longer_saves_external_path(tmp_path):
    source = tmp_path / "user.ini"
    source.write_text("version = 1\n[a]\nhf-repo = owner/model\n", encoding="utf-8")
    saved = Mock()
    config = SimpleNamespace(models_preset="")
    manager = manager_module.LlamaCppModelManager(config, cache_dir=tmp_path / "managed", supervisor=Mock(), set_preset_fn=saved)
    manager._catalog.upsert(models.LlamaModelRecord("old", "owner/old", "hugging_face"))
    summary = manager.import_preset(source)
    assert {r.model_id for r in manager._catalog.list_records()} == {"a", "old"}
    assert summary.model_ids == ("a",)
    assert config.models_preset == ""
    saved.assert_not_called()


def test_settings_replacement_and_reset_do_not_reappear(tmp_path):
    catalog = models.LlamaModelCatalog(tmp_path)
    catalog.upsert(models.LlamaModelRecord("a", "owner/a", "hugging_face"))
    catalog.update_options("a", {"cache-type-k": "q8_0", "n-cpu-moe": "4"})
    assert "n-cpu-moe = 4" in catalog.write_preset().read_text(encoding="utf-8")
    catalog.update_options("a", {})
    assert "n-cpu-moe" not in catalog.write_preset().read_text(encoding="utf-8")
    assert not models.LlamaModelCatalog(tmp_path).find_exact("a").preset_options


@pytest.mark.parametrize("options", [{"n-cpu-moe": "-1"}, {"cache-type-k": "wrong"}, {"cpu-moe": "true", "n-cpu-moe": "2"}])
def test_invalid_options_do_not_change_catalog(tmp_path, options):
    catalog = models.LlamaModelCatalog(tmp_path)
    catalog.upsert(models.LlamaModelRecord("a", "owner/a", "hugging_face"))
    before = (tmp_path / "models.json").read_bytes()
    with pytest.raises(ValueError):
        catalog.update_options("a", options)
    assert (tmp_path / "models.json").read_bytes() == before


def test_export_defaults_do_not_override_model_context_or_persist(tmp_path):
    catalog = models.LlamaModelCatalog(tmp_path)
    catalog.upsert(models.LlamaModelRecord("a", "owner/a", "hugging_face", preset_options={"ctx-size": "4096"}))
    catalog.upsert(models.LlamaModelRecord("b", "owner/b", "hugging_face"))
    exported = {r.model_id: r for r in catalog.export_records(default_context=8192)}
    assert exported["a"].preset_options["ctx-size"] == "4096"
    assert exported["b"].preset_options["ctx-size"] == "8192"
    assert catalog.find_exact("b").preset_options == {}


def test_worker_export_removes_stale_sections_and_options(tmp_path):
    worker = load_addon_module("worker.executors.llama", namespace="preset_migration")
    assert worker.default_preset_file().name == "runtime-models.ini"
    target = tmp_path / "runtime.ini"
    target.write_text("version = 1\n[removed]\nhf-repo = owner/removed\n[a]\nhf-repo = owner/old\nn-cpu-moe = 9\n", encoding="utf-8")
    worker.LlamaWorkerExecutor(supervisor=Mock()).configure_preset(
        [{"model_id": "a", "source": "owner/new", "kind": "hugging_face"}], preset_path=target)
    result = target.read_text(encoding="utf-8")
    assert "removed" not in result
    assert "n-cpu-moe" not in result
    assert "owner/new" in result


def test_legacy_manifest_and_user_preset_migrate_without_restoring_removed_ids(tmp_path):
    import json
    import hashlib
    source = tmp_path / "user.ini"
    source.write_text("version = 1\n[a]\nhf-repo = owner/a\nctx-size = 4096\n[b]\nhf-repo = owner/b\n", encoding="utf-8")
    directory = tmp_path / "managed"
    directory.mkdir()
    suffix = hashlib.sha256(str(source.resolve()).encode()).hexdigest()[:16]
    (directory / f"models-{suffix}.json").write_text(json.dumps({"version": 1, "models": [], "removed_models": ["b"]}), encoding="utf-8")
    catalog = models.LlamaModelCatalog(directory, preset_path=source)
    assert [r.model_id for r in catalog.list_records()] == ["a"]
    source.unlink()
    assert models.LlamaModelCatalog(directory).find_exact("a").preset_options == {"ctx-size": "4096"}


def test_runtime_help_rejects_new_flags_before_writing_preset(tmp_path, monkeypatch):
    worker = load_addon_module("worker.executors.llama", namespace="preset_migration")
    executor = worker.LlamaWorkerExecutor(supervisor=Mock())
    monkeypatch.setattr(executor, "inspect_options", lambda executable: {"cache-type-k"})
    target = tmp_path / "runtime.ini"
    target.write_text("original", encoding="utf-8")
    with pytest.raises(ValueError, match="moe-cache-mib"):
        executor.configure_preset([{"model_id": "a", "source": "owner/a", "kind": "hugging_face", "preset_options": {"moe-cache-mib": "1024"}}],
                                  preset_path=target, executable="llama-server")
    assert target.read_text(encoding="utf-8") == "original"


def test_runtime_help_cache_invalidates_when_binary_changes(tmp_path, monkeypatch):
    worker = load_addon_module("worker.executors.llama", namespace="preset_migration")
    executable = tmp_path / "llama-server.exe"
    executable.write_bytes(b"fixture")
    process = Mock(returncode=0)
    process.communicate.return_value = (b"--cache-type-k TYPE\n--n-cpu-moe N\n", None)
    process.poll.return_value = 0
    spawn = Mock(return_value=process)
    monkeypatch.setattr(worker.subprocess, "Popen", spawn)
    executor = worker.LlamaWorkerExecutor(supervisor=Mock())
    assert {"cache-type-k", "n-cpu-moe"} <= executor.inspect_options(str(executable))
    executor.inspect_options(str(executable))
    assert spawn.call_count == 1
    executable.write_bytes(b"new fixture")
    executor.inspect_options(str(executable))
    assert spawn.call_count == 2


def test_runtime_help_resolves_scoop_shim_target(tmp_path, monkeypatch):
    worker = load_addon_module("worker.executors.llama", namespace="preset_migration")
    shim = tmp_path / "shim.exe"
    shim.write_bytes(b"shim")
    target = tmp_path / "real.exe"
    target.write_bytes(b"binary")
    shim.with_suffix(".shim").write_text(f'path = "{target}"\n', encoding="utf-8")
    process = Mock(returncode=0)
    process.poll.return_value = 0
    process.communicate.return_value = (b"--cache-type-k TYPE", None)
    spawn = Mock(return_value=process)
    monkeypatch.setattr(worker.subprocess, "Popen", spawn)
    worker.LlamaWorkerExecutor(supervisor=Mock()).inspect_options(str(shim))
    assert spawn.call_args.args[0] == [str(target), "--help"]


def test_import_aliases_and_comments_roundtrip_without_source_mutation(tmp_path):
    source = tmp_path / "preset.ini"
    original = "version = 1\n[*]\n; example = ignored\nc = 4096\n[local]\nmodel = local.gguf\nngl = 12\nctk = q8_0\n"
    source.write_text(original, encoding="utf-8")
    catalog = models.LlamaModelCatalog(tmp_path / "managed")
    catalog.import_preset(source)
    options = catalog.find_exact("local").preset_options
    assert options == {"ctx-size": "4096", "gpu-layers": "12", "cache-type-k": "q8_0"}
    assert source.read_text(encoding="utf-8") == original
