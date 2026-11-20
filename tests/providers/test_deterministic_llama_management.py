import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.support import load_addon_module

NAMESPACE = "deterministic_llama_tests"
models = load_addon_module("providers.runtime.llama_models", namespace=NAMESPACE)
manager_module = load_addon_module("providers.llama_manager", namespace=NAMESPACE)
preset = load_addon_module("core.llama_preset", namespace=NAMESPACE)


def record(model_id="demo", repo="owner/model"):
    return models.LlamaModelRecord(model_id, repo)


def test_codec_generation_is_order_independent():
    codec = preset.LlamaPresetCodec()
    assert codec.encode([record("z"), record("a", "owner/a")]) == codec.encode([record("a", "owner/a"), record("z")])


def test_codec_rejects_legacy_local_sources_and_unknown_keys():
    codec = preset.LlamaPresetCodec()
    with pytest.raises(ValueError, match="Unsupported preset key"):
        codec.validate("version = 1\n[local]\nmodel = C:/model.gguf\n")
    with pytest.raises(ValueError, match="hf-repo is required"):
        codec.validate("version = 1\n[local]\nctx-size = 4096\n")


def test_codec_rejects_quant_with_exact_file_and_orphan_draft_file():
    codec = preset.LlamaPresetCodec()
    with pytest.raises(ValueError, match="quant suffix"):
        codec.validate("version = 1\n[a]\nhf-repo = owner/model:Q4_K_M\nhf-file = model.gguf\n")
    with pytest.raises(ValueError, match="requires spec-draft-hf"):
        codec.validate("version = 1\n[a]\nhf-repo = owner/model\nspec-draft-model = draft.gguf\n")


def test_catalog_does_not_read_user_preset(tmp_path):
    source = tmp_path / "user.ini"
    original = "version = 1\n[local]\nmodel = missing.gguf\ncache-type-k = q8_0\n"
    source.write_text(original, encoding="utf-8")
    catalog = models.LlamaModelCatalog(tmp_path / "managed")
    assert catalog.list_records() == ()
    assert catalog.write_preset().read_text(encoding="utf-8") == "version = 1\n"
    catalog.upsert(record())
    catalog.remove("demo")
    assert source.read_text(encoding="utf-8") == original
    assert not catalog.list_records()


def test_manager_crud_and_selection(tmp_path):
    supervisor = Mock()
    saved = []
    config = SimpleNamespace(model_name="")
    manager = manager_module.LlamaCppModelManager(config=config, cache_dir=tmp_path,
        supervisor=supervisor, set_model_fn=saved.append)
    manager.create_preset("owner/model", "demo", "Demo", options={"ctx-size": "4096"}, select=True)
    assert saved == ["demo"]
    assert manager.active_model_id == "demo"
    manager.update_preset("demo", repo="owner/new", display_name="New name", options={"ctx-size": "8192"})
    assert manager.list_presets()[0].repo == "owner/new"
    assert manager.list_presets()[0].display_name == "New name"
    manifest = json.loads((tmp_path / "models.json").read_text(encoding="utf-8"))
    assert manifest["models"][0]["repo"] == "owner/new"
    assert manifest["models"][0]["preset_options"]["ctx-size"] == "8192"
    generated = (tmp_path / "runtime-models.ini").read_text(encoding="utf-8")
    assert "hf-repo = owner/new" in generated
    assert "ctx-size = 8192" in generated
    manager.duplicate_preset("demo", "copy", "Copy")
    assert [item.model_id for item in manager.list_presets()] == ["copy", "demo"]
    manager.delete_model("demo")
    assert manager.active_model_id is None
    assert [item.model_id for item in manager.list_presets()] == ["copy"]


def test_manager_rejects_duplicate_ids_and_unknown_delete(tmp_path):
    manager = manager_module.LlamaCppModelManager(cache_dir=tmp_path, supervisor=Mock())
    manager.create_preset("owner/model", "demo", "Demo")
    with pytest.raises(ValueError, match="already exists"):
        manager.create_preset("owner/other", "demo", "Other")
    with pytest.raises(manager_module.LLMProviderError):
        manager.delete_model("missing")
