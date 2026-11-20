import json
from unittest.mock import Mock

import pytest

from tests.support import load_addon_module

models = load_addon_module("providers.runtime.llama_models", namespace="catalog_only")
manager_module = load_addon_module("providers.llama_manager", namespace="catalog_only")
options_module = load_addon_module("core.llama_options", namespace="catalog_only")


def record(model_id="a", repo="owner/a", **kwargs):
    return models.LlamaModelRecord(model_id, repo, **kwargs)


def test_external_preset_is_never_imported(tmp_path):
    source = tmp_path / "user.ini"
    source.write_text("version = 1\n[a]\nhf-repo = owner/a\n", encoding="utf-8")
    catalog = models.LlamaModelCatalog(tmp_path / "managed")
    assert catalog.list_records() == ()
    assert not (tmp_path / "managed/models.json").exists()


def test_old_manifest_is_ignored_without_migration(tmp_path):
    directory = tmp_path / "managed"
    directory.mkdir()
    (directory / "models.json").write_text(json.dumps({"version": 1, "models": [
        {"model_id": "a", "source": "owner/a", "kind": "hugging_face"},
    ]}), encoding="utf-8")
    assert models.LlamaModelCatalog(directory).list_records() == ()


def test_explicit_preset_round_trips_options(tmp_path):
    catalog = models.LlamaModelCatalog(tmp_path)
    catalog.upsert(record(preset_options={"kv-unified": "true", "temperature": "0.6"}))
    reloaded = models.LlamaModelCatalog(tmp_path).find_exact("a")
    assert reloaded.preset_options == {"kv-unified": "true", "temperature": "0.6"}
    assert reloaded.repo == "owner/a"


def test_settings_replacement_and_reset_do_not_reappear(tmp_path):
    catalog = models.LlamaModelCatalog(tmp_path)
    catalog.upsert(record())
    catalog.update_options("a", {"cache-type-k": "q8_0", "n-cpu-moe": "4"})
    assert "n-cpu-moe = 4" in catalog.write_preset().read_text(encoding="utf-8")
    catalog.update_options("a", {})
    assert "n-cpu-moe" not in catalog.write_preset().read_text(encoding="utf-8")
    assert not models.LlamaModelCatalog(tmp_path).find_exact("a").preset_options


@pytest.mark.parametrize("options", [
    {"n-cpu-moe": "-1"},
    {"cache-type-k": "wrong"},
    {"cpu-moe": "true", "n-cpu-moe": "2"},
    {"temperature": "not-a-number"},
    {"top-p": "1.5"},
])
def test_invalid_options_do_not_change_catalog(tmp_path, options):
    catalog = models.LlamaModelCatalog(tmp_path)
    catalog.upsert(record())
    before = (tmp_path / "models.json").read_bytes()
    with pytest.raises(ValueError):
        catalog.update_options("a", options)
    assert (tmp_path / "models.json").read_bytes() == before


def test_export_defaults_do_not_override_model_context_or_persist(tmp_path):
    catalog = models.LlamaModelCatalog(tmp_path)
    catalog.upsert(record(preset_options={"ctx-size": "4096"}))
    catalog.upsert(record("b", "owner/b"))
    exported = {item.model_id: item for item in catalog.export_records(default_context=8192)}
    assert exported["a"].preset_options["ctx-size"] == "4096"
    assert exported["b"].preset_options["ctx-size"] == "8192"
    assert catalog.find_exact("b").preset_options == {}


def test_generated_preset_contains_hf_source_only(tmp_path):
    catalog = models.LlamaModelCatalog(tmp_path)
    catalog.upsert(record(file="weights.gguf", draft_repo="owner/draft", draft_file="draft.gguf",
        preset_options={"spec-type": "draft-mtp", "ctx-size": "4096"}))
    text = catalog.write_preset().read_text(encoding="utf-8")
    assert "hf-repo = owner/a" in text
    assert "hf-file = weights.gguf" in text
    assert "spec-draft-hf = owner/draft" in text
    assert "spec-draft-model = draft.gguf" in text
    assert "\nmodel = " not in text
    assert "\nmmproj = " not in text


def test_worker_export_removes_stale_sections_and_options(tmp_path):
    worker = load_addon_module("worker.executors.llama", namespace="catalog_only")
    assert worker.default_preset_file().name == "runtime-models.ini"
    target = tmp_path / "runtime.ini"
    target.write_text("version = 1\n[removed]\nhf-repo = owner/removed\n[a]\nhf-repo = owner/old\nn-cpu-moe = 9\n", encoding="utf-8")
    worker.LlamaWorkerExecutor(supervisor=Mock()).configure_preset(
        [{"model_id": "a", "repo": "owner/new"}], preset_path=target)
    result = target.read_text(encoding="utf-8")
    assert "removed" not in result
    assert "n-cpu-moe" not in result
    assert "owner/new" in result


def test_runtime_help_rejects_new_flags_before_writing_preset(tmp_path, monkeypatch):
    worker = load_addon_module("worker.executors.llama", namespace="catalog_only")
    executor = worker.LlamaWorkerExecutor(supervisor=Mock())
    monkeypatch.setattr(executor, "inspect_options", lambda executable: {"cache-type-k"})
    target = tmp_path / "runtime.ini"
    target.write_text("original", encoding="utf-8")
    with pytest.raises(ValueError, match="moe-cache-mib"):
        executor.configure_preset([{"model_id": "a", "repo": "owner/a", "preset_options": {"moe-cache-mib": "1024"}}],
                                  preset_path=target, executable="llama-server")
    assert target.read_text(encoding="utf-8") == "original"


def test_alias_and_latest_flags_validate_to_canonical_keys():
    validated = options_module.validate_options({
        "lm": "mlock", "temp": "0.7", "c": "4096",
        "kv-unified": "true", "ctx-checkpoints": "8", "spec-draft-n-max": "2",
    })
    assert validated == {
        "load-mode": "mlock", "temperature": "0.7", "ctx-size": "4096",
        "kv-unified": "true", "ctx-checkpoints": "8", "spec-draft-n-max": "2",
    }


def test_requested_moe_cache_flags_and_output_limit_roundtrip(tmp_path):
    validated = options_module.validate_options({
        "cpu-moe": "true", "load-mode": "none", "moe-cache-mib": "3264",
        "moe-cache-cpu-share": "0.95", "ngl": "99", "fa": "on",
        "c": "4096", "n": "512", "temp": "0",
    })
    catalog = models.LlamaModelCatalog(tmp_path)
    catalog.upsert(record(preset_options=validated))
    exported = catalog.write_preset().read_text(encoding="utf-8")
    for key, value in validated.items():
        assert f"{key} = {value}" in exported
    assert validated["n-predict"] == "512"
    assert validated["temperature"] == "0.0"


@pytest.mark.parametrize("key", ["n", "predict", "n-predict"])
def test_prediction_limit_aliases_and_range(key):
    assert options_module.validate_options({key: "-1"}) == {"n-predict": "-1"}
    with pytest.raises(ValueError):
        options_module.validate_options({key: "-2"})


def test_manager_has_only_hf_preset_operations(tmp_path):
    manager = manager_module.LlamaCppModelManager(cache_dir=tmp_path / "managed", supervisor=Mock())
    for name in ("import_preset", "preview_preset_import", "create_configuration_from_asset",
                 "discover_assets", "delete_cached_files", "relocate_configuration"):
        assert not hasattr(manager, name)
    manager.create_preset("owner/model", "demo", "Demo")
    assert [item.model_id for item in manager.list_presets()] == ["demo"]
